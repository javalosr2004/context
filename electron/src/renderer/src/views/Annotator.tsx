import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import type {
  AxAttributes,
  AxAttributesPayload,
  AxBoundingBox,
  RecordedMouseEvent
} from '../../../shared/types'
import { useRecordingStore } from '../store/recordingStore'

export interface AnnotatorEvent {
  eventName: string
  timestampMs: number
  axAttributes: AxAttributesPayload
  /** Screen coordinates from the recording (physical pixels). */
  x?: number
  y?: number
  /** Index into the rawEvents array for persistence. */
  rawEventIndex: number
}

function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

async function captureScreen(sourceId: string): Promise<MediaStream> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
      mandatory: {
        chromeMediaSource: 'desktop',
        chromeMediaSourceId: sourceId,
        minWidth: 1280,
        minHeight: 720,
        maxWidth: 1920,
        maxHeight: 1080
      }
    } as MediaTrackConstraints
  })
  return stream
}

export default function Annotator(): React.JSX.Element {
  const navigate = useNavigate()
  const { archivePath, videoPath, eventsPath, isLoaded, setExtractedPaths, setArchivePath } =
    useRecordingStore()
  const [events, setEvents] = useState<AnnotatorEvent[]>([])
  const [durationMs, setDurationMs] = useState(120_000)
  const [currentTimeMs, setCurrentTimeMs] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const [videoLayoutPx, setVideoLayoutPx] = useState({ width: 0, height: 0 })
  const [videoNativePx, setVideoNativePx] = useState({ width: 0, height: 0 })
  const [activeEventIdx, setActiveEventIdx] = useState<number | null>(null)
  const [expandedEventIdx, setExpandedEventIdx] = useState<number | null>(null)
  const [activeNodeKey, setActiveNodeKey] = useState('current')
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  /** Raw events from disk, used for save. Mirrors sortedEvents order but as RecordedMouseEvent[]. */
  const [rawEvents, setRawEvents] = useState<RecordedMouseEvent[]>([])
  const rafIdRef = useRef<number | null>(null)
  const eventTooltipTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const eventTooltipPointerRef = useRef({ clientX: 0, clientY: 0 })
  const [eventTooltip, setEventTooltip] = useState<{
    x: number
    y: number
    left: number
    top: number
  } | null>(null)

  // Recording state
  const [isRecording, setIsRecording] = useState(false)
  const [isRecordingLoading, setIsRecordingLoading] = useState(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const writePromisesRef = useRef<Promise<void>[]>([])

  // Cleanup recorder and stream on unmount
  useEffect(() => {
    return () => {
      const recorder = recorderRef.current
      if (recorder && recorder.state !== 'inactive') {
        recorder.stop()
      }
      streamRef.current?.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
  }, [])

  useEffect(() => {
    const el = videoRef.current
    if (!el) return

    const ro = new ResizeObserver(() => {
      const rect = el.getBoundingClientRect()
      setVideoLayoutPx({
        width: Math.round(rect.width),
        height: Math.round(rect.height)
      })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [videoPath])

  const clearEventTooltipTimer = useCallback((): void => {
    if (eventTooltipTimerRef.current !== null) {
      clearTimeout(eventTooltipTimerRef.current)
      eventTooltipTimerRef.current = null
    }
  }, [])

  useEffect(() => {
    return () => clearEventTooltipTimer()
  }, [clearEventTooltipTimer])

  const scheduleEventTooltip = useCallback(
    (evt: AnnotatorEvent): void => {
      clearEventTooltipTimer()
      const x = evt.x
      const y = evt.y
      if (x === undefined || y === undefined || Number.isNaN(x) || Number.isNaN(y)) {
        return
      }
      eventTooltipTimerRef.current = setTimeout(() => {
        eventTooltipTimerRef.current = null
        const { clientX, clientY } = eventTooltipPointerRef.current
        setEventTooltip({ x, y, left: clientX, top: clientY })
      }, 1000)
    },
    [clearEventTooltipTimer]
  )

  const handleEventHoverMove = useCallback((e: React.MouseEvent): void => {
    eventTooltipPointerRef.current = { clientX: e.clientX, clientY: e.clientY }
  }, [])

  const handleEventHoverEnter = useCallback(
    (evt: AnnotatorEvent, e: React.MouseEvent): void => {
      eventTooltipPointerRef.current = { clientX: e.clientX, clientY: e.clientY }
      scheduleEventTooltip(evt)
    },
    [scheduleEventTooltip]
  )

  const handleEventHoverLeave = useCallback((): void => {
    clearEventTooltipTimer()
    setEventTooltip(null)
  }, [clearEventTooltipTimer])

  const handleImportCtx = async (): Promise<void> => {
    const result = await window.api.showOpenRecordingDialog()
    if (!result.ok) {
      if (result.error !== 'Dialog canceled') {
        setError(result.error)
      }
      return
    }
    setError(null)
    setEvents([])
    setArchivePath(result.payload.filePath)
  }

  const handleStartRecording = async (): Promise<void> => {
    if (!window.api) {
      setError('Not running in Electron')
      return
    }

    setIsRecordingLoading(true)
    setError(null)

    if (!isRecording) {
      const sourcesResult = await window.api.getSources()
      if (!sourcesResult.ok) {
        setError(sourcesResult.error)
        setIsRecordingLoading(false)
        return
      }
      const sources = sourcesResult.payload

      const displayResult = await window.api.getCursorDisplay()
      if (!displayResult.ok) {
        setError(displayResult.error)
        setIsRecordingLoading(false)
        return
      }
      const curDisplay = displayResult.payload

      let sourceId: string | undefined
      for (const source of sources) {
        if (source.displayId === String(curDisplay.id)) {
          sourceId = source.id
        }
      }

      if (!sourceId) {
        setError('No screen sources found.')
        setIsRecordingLoading(false)
        return
      }

      const stream = await captureScreen(sourceId)
      streamRef.current = stream

      const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
        ? 'video/webm;codecs=vp9'
        : 'video/webm'

      const res = await window.api.startRecording()
      if (!res.ok) {
        setError(res.error)
        setIsRecordingLoading(false)
        return
      }

      const recorder = new MediaRecorder(stream, { mimeType })
      recorderRef.current = recorder
      writePromisesRef.current = []

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          const writePromise = (async () => {
            const dataArrBuffer = await event.data.arrayBuffer()
            const result = await window.api.pushRecordingChunk(dataArrBuffer)
            if (!result.ok) {
              console.error('Failed to push recording chunk:', result.error)
              setError(result.error)
              throw new Error(result.error)
            }
          })()
          writePromisesRef.current.push(writePromise)
        }
      }

      recorder.start()
      setIsRecording(true)
    } else {
      // Stop recording
      const recorder = recorderRef.current
      if (recorder && recorder.state !== 'inactive') {
        await new Promise<void>((resolve) => {
          recorder.onstop = async () => {
            await Promise.allSettled(writePromisesRef.current)
            resolve()
          }
          recorder.stop()
        })
      }
      writePromisesRef.current = []

      streamRef.current?.getTracks().forEach((track) => track.stop())
      streamRef.current = null

      const defaultName = 'recording.webm'
      const result = await window.api.finishRecording(defaultName)
      if (result.ok) {
        // Automatically load the new recording
        setEvents([])
        setArchivePath(result.payload.zipPath)
      } else {
        if (result.error !== 'Save canceled') {
          setError(result.error)
        }
      }

      setIsRecording(false)
    }

    setIsRecordingLoading(false)
  }

  // Load the recording when archivePath changes
  useEffect(() => {
    if (!archivePath || isLoaded) return

    const loadRecording = async (): Promise<void> => {
      setIsLoading(true)
      setError(null)

      try {
        const result = await window.api.importRecording(archivePath)
        if (result.ok) {
          const { videoPath: importedVideoPath, eventsPath: importedEventsPath, events: rawEvents } = result.payload

          // Transform Rust events to AnnotatorEvents with relative timestamps
          if (rawEvents.length > 0) {
            // Use recording_start event as baseline, fall back to first event
            const startEvent = rawEvents.find((e) => e.eventType === 'recording_start')
            if (!startEvent) {
              setError('Failed to load startTime of video.')
              setIsLoading(false)
              return
            }
            setExtractedPaths(importedVideoPath, importedEventsPath)

            const startTimeMs = Number(startEvent?.timeUtcMs ?? rawEvents[0].timeUtcMs)

            // Filter out the synthetic recording_start event from display
            const annotatorEvents: AnnotatorEvent[] = rawEvents
              .map((evt, idx) => ({ evt, idx }))
              .filter(({ evt }) => evt.eventType !== 'recording_start')
              .map(({ evt, idx }) => ({
                eventName: evt.eventType,
                timestampMs: Number(evt.timeUtcMs) - startTimeMs,
                axAttributes: evt.axAttributes ?? {},
                x: evt.x,
                y: evt.y,
                rawEventIndex: idx
              }))
            setEvents(annotatorEvents)
            setRawEvents(rawEvents)
            setHasUnsavedChanges(false)
          }
        } else {
          setError(result.error)
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setIsLoading(false)
      }
    }

    loadRecording()
  }, [archivePath, isLoaded, setExtractedPaths])

  // Update duration when video metadata loads
  const handleLoadedMetadata = (): void => {
    if (videoRef.current) {
      setDurationMs(videoRef.current.duration * 1000)
      setVideoNativePx({
        width: videoRef.current.videoWidth,
        height: videoRef.current.videoHeight
      })
    }
  }

  // Use requestAnimationFrame for smooth time tracking
  useEffect(() => {
    const updateTime = (): void => {
      if (videoRef.current) {
        setCurrentTimeMs(videoRef.current.currentTime * 1000)
      }
      rafIdRef.current = requestAnimationFrame(updateTime)
    }

    rafIdRef.current = requestAnimationFrame(updateTime)

    return () => {
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current)
      }
    }
  }, [])

  const seekToTime = useCallback((timeMs: number): void => {
    if (!videoRef.current) return
    videoRef.current.currentTime = timeMs / 1000
    setCurrentTimeMs(timeMs)
  }, [])

  const handleTimelineClick = (e: React.MouseEvent<HTMLDivElement>): void => {
    if (!videoRef.current || durationMs <= 0) return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX - rect.left
    const pct = Math.max(0, Math.min(1, x / rect.width))
    const timeMs = pct * durationMs
    seekToTime(timeMs)
  }

  const sortedEvents = useMemo(
    () => [...events].sort((a, b) => a.timestampMs - b.timestampMs),
    [events]
  )

  /** Determine which node key has `selected: true`, falling back to 'current'. */
  const resolveSelectedNodeKey = useCallback(
    (idx: number): string => {
      const evt = sortedEvents[idx]
      if (!evt) return 'current'
      const snap = evt.axAttributes as
        | { current?: AxAttributes; parents?: AxAttributes[]; children?: AxAttributes[] }
        | undefined
      if (!snap) return 'current'
      if (snap.parents) {
        for (let i = 0; i < snap.parents.length; i++) {
          if (snap.parents[i].selected) return `parent-${i}`
        }
      }
      if (snap.children) {
        for (let i = 0; i < snap.children.length; i++) {
          if (snap.children[i].selected) return `child-${i}`
        }
      }
      return 'current'
    },
    [sortedEvents]
  )

  const handleEventClick = useCallback(
    (timestampMs: number, idx: number): void => {
      seekToTime(timestampMs)
      setActiveEventIdx(idx)
      setActiveNodeKey(resolveSelectedNodeKey(idx))
    },
    [seekToTime, resolveSelectedNodeKey]
  )

  const handleEventDoubleClick = useCallback(
    (timestampMs: number, idx: number): void => {
      seekToTime(timestampMs)
      setActiveEventIdx(idx)
      setExpandedEventIdx(idx)
      setActiveNodeKey(resolveSelectedNodeKey(idx))
    },
    [seekToTime, resolveSelectedNodeKey]
  )

  const handleCollapseTree = useCallback((): void => {
    setExpandedEventIdx(null)
  }, [])

  /** Update `selected` on nodes within the event's axAttributes when the user picks a node. */
  const selectNode = useCallback(
    (nodeKey: string): void => {
      setActiveNodeKey(nodeKey)
      if (expandedEventIdx === null || expandedEventIdx >= events.length) return

      const evt = events[expandedEventIdx]
      const snap = evt.axAttributes as
        | { current?: AxAttributes; parents?: AxAttributes[]; children?: AxAttributes[] }
        | undefined
      if (!snap?.current) return

      // Helper: clear all, then set the chosen node
      const applySelection = (
        s: { current?: AxAttributes; parents?: AxAttributes[]; children?: AxAttributes[] }
      ): void => {
        if (s.current) s.current.selected = undefined
        s.parents?.forEach((p) => (p.selected = undefined))
        s.children?.forEach((c) => (c.selected = undefined))

        if (nodeKey === 'current') {
          if (s.current) s.current.selected = true
        } else {
          const [kind, idxStr] = nodeKey.split('-')
          const idx = Number(idxStr)
          const list = kind === 'parent' ? s.parents : s.children
          if (list?.[idx]) list[idx].selected = true
        }
      }

      // Update annotator event snapshot
      applySelection(snap)

      // Mirror into rawEvents for persistence
      const rawSnap = rawEvents[evt.rawEventIndex]?.axAttributes as typeof snap | undefined
      if (rawSnap?.current) applySelection(rawSnap)

      setHasUnsavedChanges(true)
    },
    [expandedEventIdx, events, rawEvents]
  )

  const handleSave = useCallback(async (): Promise<void> => {
    if (!eventsPath || !archivePath || rawEvents.length === 0) return
    const result = await window.api.saveEvents(eventsPath, archivePath, rawEvents)
    if (result.ok) {
      setHasUnsavedChanges(false)
    } else {
      setError(result.error)
    }
  }, [eventsPath, archivePath, rawEvents])

  const scale = videoNativePx.width > 0 ? videoLayoutPx.width / videoNativePx.width : 1

  // Auto-activate the nearest event when the playhead is within ±200ms
  const BBOX_WINDOW_MS = 200
  const timeWindowEventIdx: number | null = useMemo(() => {
    if (sortedEvents.length === 0) return null
    let closest: { idx: number; dist: number } | null = null
    for (let i = 0; i < sortedEvents.length; i++) {
      const dist = Math.abs(sortedEvents[i].timestampMs - currentTimeMs)
      if (dist <= BBOX_WINDOW_MS && (!closest || dist < closest.dist)) {
        closest = { idx: i, dist }
      }
    }
    return closest?.idx ?? null
  }, [sortedEvents, currentTimeMs])

  // Clear manual selection when playhead drifts beyond the window
  useEffect(() => {
    if (activeEventIdx === null || activeEventIdx >= sortedEvents.length) return
    const dist = Math.abs(sortedEvents[activeEventIdx].timestampMs - currentTimeMs)
    if (dist > BBOX_WINDOW_MS) {
      setActiveEventIdx(null)
    }
  }, [currentTimeMs, activeEventIdx, sortedEvents])

  // Prefer manual selection (activeEventIdx), fall back to time-windowed
  const displayEventIdx = activeEventIdx ?? timeWindowEventIdx

  const activeSnapshot = useMemo(() => {
    if (displayEventIdx === null || displayEventIdx >= sortedEvents.length) return null
    const attrs = sortedEvents[displayEventIdx].axAttributes as
      | {
          current?: AxAttributes
          parents?: AxAttributes[]
          children?: AxAttributes[]
        }
      | undefined
    if (!attrs?.current) return null
    return attrs as { current: AxAttributes; parents: AxAttributes[]; children: AxAttributes[] }
  }, [displayEventIdx, sortedEvents])

  // Use manual selection key when user clicked, otherwise resolve from persisted `selected`
  const displayNodeKey = useMemo(() => {
    if (activeEventIdx !== null) return activeNodeKey
    if (displayEventIdx !== null) return resolveSelectedNodeKey(displayEventIdx)
    return 'current'
  }, [activeEventIdx, activeNodeKey, displayEventIdx, resolveSelectedNodeKey])

  const activeBbox: AxBoundingBox | null = useMemo(() => {
    if (!activeSnapshot) return null
    if (displayNodeKey === 'current') return activeSnapshot.current.boundingBox ?? null
    const [kind, idxStr] = displayNodeKey.split('-')
    const idx = Number(idxStr)
    const list = kind === 'parent' ? activeSnapshot.parents : activeSnapshot.children
    return list?.[idx]?.boundingBox ?? null
  }, [activeSnapshot, displayNodeKey])

  return (
    <div className="ann">
      {/* Noise grain overlay */}
      <div className="dash-grain" aria-hidden="true" />

      {/* Main content: video + timeline */}
      <div className="ann-main">
        {/* Toolbar */}
        <div className="ann-toolbar">
          <button type="button" onClick={() => navigate('/')} className="ann-btn ann-btn-ghost">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-4 w-4"
            >
              <polyline points="15 18 9 12 15 6" />
            </svg>
            Back
          </button>

          <div className="ann-toolbar-actions">
            <button
              type="button"
              onClick={handleStartRecording}
              disabled={isRecordingLoading || isLoading}
              className={`ann-btn ${isRecording ? 'ann-btn-stop' : 'ann-btn-record'}`}
            >
              {isRecordingLoading ? (
                <span className="ann-spinner" />
              ) : isRecording ? (
                <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                  <circle cx="12" cy="12" r="6" />
                </svg>
              )}
              {isRecording ? 'Stop Recording' : 'Start Recording'}
            </button>
            <button
              type="button"
              onClick={handleImportCtx}
              disabled={isLoading || isRecording}
              className="ann-btn ann-btn-secondary"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-4 w-4"
              >
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              Import .ctx
            </button>
            {isLoaded && (
              <button
                type="button"
                onClick={handleSave}
                disabled={!hasUnsavedChanges}
                className="ann-btn ann-btn-save"
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-4 w-4"
                >
                  <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                  <polyline points="17 21 17 13 7 13 7 21" />
                  <polyline points="7 3 7 8 15 8" />
                </svg>
                Save
              </button>
            )}
          </div>
        </div>

        {/* Video area */}
        <div className="ann-video-area">
          {isLoading ? (
            <div className="ann-empty">
              <div className="ann-spinner ann-spinner-lg" />
              <span className="ann-empty-text">Loading recording...</span>
            </div>
          ) : error ? (
            <div className="ann-empty">
              <span className="ann-error-text">{error}</span>
            </div>
          ) : videoPath ? (
            <div>
              <div style={{ position: 'relative', display: 'inline-block' }}>
                <video
                  ref={videoRef}
                  src={`media://local/${encodeURIComponent(videoPath)}`}
                  className="max-w-full max-h-full"
                  controls
                  onLoadedMetadata={handleLoadedMetadata}
                />
                {activeBbox && (
                  <div
                    style={{
                      position: 'absolute',
                      left: activeBbox.x * scale,
                      top: activeBbox.y * scale,
                      width: activeBbox.width * scale,
                      height: activeBbox.height * scale,
                      border: '2px solid #ff3b30',
                      backgroundColor: 'rgba(255, 59, 48, 0.15)',
                      borderRadius: 3,
                      pointerEvents: 'none'
                    }}
                  />
                )}
              </div>
              <h1 className="ann-video-dimensions">
                {videoNativePx.width} × {videoNativePx.height} native | {videoLayoutPx.width} ×{' '}
                {videoLayoutPx.height} layout | scale: {scale.toFixed(3)}
              </h1>
            </div>
          ) : (
            <div className="ann-empty">
              <div className="ann-empty-icon">
                <svg
                  viewBox="0 0 48 48"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  className="w-12 h-12"
                >
                  <rect x="6" y="10" width="36" height="28" rx="4" />
                  <circle cx="24" cy="24" r="6" />
                  <circle cx="24" cy="24" r="2" fill="currentColor" />
                </svg>
              </div>
              <span className="ann-empty-title">No Recording</span>
              <span className="ann-empty-text">Record a session or import a .ctx file</span>
              <button
                type="button"
                onClick={handleImportCtx}
                disabled={isLoading}
                className="ann-btn ann-btn-primary"
              >
                Import .ctx file
              </button>
            </div>
          )}
        </div>

        {/* Timeline */}
        <div
          role="slider"
          aria-label="Video timeline"
          aria-valuemin={0}
          aria-valuemax={durationMs}
          aria-valuenow={currentTimeMs}
          tabIndex={0}
          onClick={handleTimelineClick}
          className="ann-timeline"
        >
          {/* Track fill */}
          <div
            className="ann-timeline-fill"
            style={{
              width: durationMs > 0 ? `${(currentTimeMs / durationMs) * 100}%` : '0%'
            }}
          />
          {/* Event markers */}
          {durationMs > 0 &&
            sortedEvents.map((evt, i) => {
              const positionPercent = Math.min(
                100,
                Math.max(0, (evt.timestampMs / durationMs) * 100)
              )
              return (
                <div
                  key={`${evt.timestampMs}-${i}`}
                  className="ann-timeline-marker-hit"
                  style={{ left: `${positionPercent}%` }}
                  onMouseEnter={(e) => handleEventHoverEnter(evt, e)}
                  onMouseMove={handleEventHoverMove}
                  onMouseLeave={handleEventHoverLeave}
                >
                  <div className="ann-timeline-marker" aria-hidden />
                </div>
              )
            })}
          {/* Playhead */}
          {durationMs > 0 && (
            <div
              className="ann-timeline-playhead"
              style={{ left: `${(currentTimeMs / durationMs) * 100}%` }}
            />
          )}
          {/* Time labels */}
          <div className="ann-timeline-time">
            {formatTimestamp(currentTimeMs)} / {formatTimestamp(durationMs)}
          </div>
        </div>
      </div>

      {/* Events sidebar */}
      <aside className="ann-sidebar">
        {expandedEventIdx !== null && activeSnapshot ? (
          <>
            <div className="ann-sidebar-head">
              <button
                type="button"
                onClick={handleCollapseTree}
                className="ann-btn ann-btn-ghost"
                style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-3 w-3"
                >
                  <polyline points="15 18 9 12 15 6" />
                </svg>
                Events
              </button>
              <span className="ann-sidebar-count">
                {formatTimestamp(sortedEvents[expandedEventIdx].timestampMs)}
              </span>
            </div>
            <div className="ann-sidebar-list">
              {/* Current (hit target) */}
              <div className="ax-tree-section">
                <div className="ax-tree-section-label">Hit Target</div>
                <div
                  className={`ax-tree-node ${activeNodeKey === 'current' ? 'ax-tree-node-active' : ''}`}
                  onClick={() => selectNode('current')}
                >
                  <span className="ax-tree-node-role">{activeSnapshot.current.axRole}</span>
                  <span className="ax-tree-node-text">
                    {activeSnapshot.current.axTitle ||
                      activeSnapshot.current.axValue ||
                      activeSnapshot.current.axDescription ||
                      activeSnapshot.current.axRoleDescription}
                  </span>
                  {activeSnapshot.current.boundingBox && (
                    <span className="ax-tree-node-bbox">bbox</span>
                  )}
                </div>
              </div>

              {/* Parents */}
              {activeSnapshot.parents.length > 0 && (
                <div className="ax-tree-section">
                  <div className="ax-tree-section-label">
                    Parents ({activeSnapshot.parents.length})
                  </div>
                  {activeSnapshot.parents.map((node, i) => {
                    const key = `parent-${i}`
                    return (
                      <div
                        key={key}
                        className={`ax-tree-node ${activeNodeKey === key ? 'ax-tree-node-active' : ''}`}
                        style={{ paddingLeft: `${0.75 + i * 0.5}rem` }}
                        onClick={() => selectNode(key)}
                      >
                        <span className="ax-tree-node-role">{node.axRole}</span>
                        <span className="ax-tree-node-text">
                          {node.axTitle ||
                            node.axValue ||
                            node.axDescription ||
                            node.axRoleDescription}
                        </span>
                        {node.boundingBox && <span className="ax-tree-node-bbox">bbox</span>}
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Children */}
              {activeSnapshot.children.length > 0 && (
                <div className="ax-tree-section">
                  <div className="ax-tree-section-label">
                    Children ({activeSnapshot.children.length})
                  </div>
                  {activeSnapshot.children.map((node, i) => {
                    const key = `child-${i}`
                    return (
                      <div
                        key={key}
                        className={`ax-tree-node ${activeNodeKey === key ? 'ax-tree-node-active' : ''}`}
                        onClick={() => selectNode(key)}
                      >
                        <span className="ax-tree-node-role">{node.axRole}</span>
                        <span className="ax-tree-node-text">
                          {node.axTitle ||
                            node.axValue ||
                            node.axDescription ||
                            node.axRoleDescription}
                        </span>
                        {node.boundingBox && <span className="ax-tree-node-bbox">bbox</span>}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="ann-sidebar-head">
              <h2 className="ann-sidebar-title">Events</h2>
              <span className="ann-sidebar-count">{sortedEvents.length}</span>
            </div>
            <div className="ann-sidebar-list">
              {sortedEvents.length === 0 ? (
                <div className="ann-sidebar-empty">No events yet</div>
              ) : (
                <ul>
                  {sortedEvents.map((evt, i) => (
                    <li
                      key={`${evt.timestampMs}-${evt.eventName}-${i}`}
                      onClick={() => handleEventClick(evt.timestampMs, i)}
                      onDoubleClick={() => handleEventDoubleClick(evt.timestampMs, i)}
                      onMouseEnter={(e) => handleEventHoverEnter(evt, e)}
                      onMouseMove={handleEventHoverMove}
                      onMouseLeave={handleEventHoverLeave}
                      className={`ann-event ${
                        evt.timestampMs <= currentTimeMs ? 'ann-event-past' : ''
                      } ${activeEventIdx === i ? 'ann-event-selected' : ''}`}
                    >
                      <span className="ann-event-dot" />
                      <div className="ann-event-info">
                        <span className="ann-event-name">{evt.eventName}</span>
                        <span className="ann-event-time">{formatTimestamp(evt.timestampMs)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        )}
      </aside>

      {eventTooltip && (
        <div
          role="tooltip"
          className="ann-event-tooltip"
          style={{
            left: eventTooltip.left + 12,
            top: eventTooltip.top + 12
          }}
        >
          x: {Math.round(eventTooltip.x)}, y: {Math.round(eventTooltip.y)}
        </div>
      )}
    </div>
  )
}
