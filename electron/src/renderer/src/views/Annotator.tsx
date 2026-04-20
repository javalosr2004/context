import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import type {
  AxAttributes,
  AxAttributesPayload,
  AxBoundingBox,
  LoadedRecordingPayload,
  RecordedMouseEvent,
  UserOverride
} from '../../../shared/types'
import { useRecordingStore } from '../store/recordingStore'

export interface AnnotatorEvent {
  eventName: string
  /** User-authored title; falls back to eventName when absent. */
  title: string
  timestampMs: number
  axAttributes: AxAttributesPayload
  /** Screen coordinates from the recording (physical pixels). */
  x?: number
  y?: number
  /** Index into the rawEvents array for persistence. */
  rawEventIndex: number
}

/**
 * Structural view over a snapshot payload. Fields are optional because older `.ctx` files
 * use the legacy flat `AxAttributeMap` shape — consumers must null-check before dereferencing.
 */
type SnapView = {
  current?: AxAttributes
  parents?: AxAttributes[]
  children?: AxAttributes[]
  userOverride?: UserOverride | null
  /** Which node is the annotation target. See selection key format below. */
  selected?: string
  title?: string | null
  description?: string | null
}

/**
 * Selection key format — a single string names which node is the annotation target.
 *
 *   "current"            → snap.current
 *   "user_override"      → snap.userOverride
 *   "parents:<index>"    → snap.parents[index]
 *   "children:<index>"   → snap.children[index]
 *
 * Centralising selection in one string (rather than a `selected: true` flag per node)
 * makes the invariant structural: exactly one thing is ever selected because there's
 * exactly one slot. No loops, no cross-node clearing, no corrupt states.
 */
const DEFAULT_SELECTED = 'current'

const PARENTS_KEY = /^parents:(\d+)$/
const CHILDREN_KEY = /^children:(\d+)$/

/** Bounding box for a given selection key, or null if missing / malformed. */
function boundingBoxForKey(snap: SnapView, key: string): AxBoundingBox | null {
  const k = key || DEFAULT_SELECTED

  if (k === 'current') {
    return snap.current?.boundingBox ?? null
  }
  if (k === 'user_override') {
    return snap.userOverride?.boundingBox ?? null
  }

  let m = PARENTS_KEY.exec(k)
  if (m) {
    const i = Number(m[1])
    const node = snap.parents?.[i]
    return node?.boundingBox ?? null
  }

  m = CHILDREN_KEY.exec(k)
  if (m) {
    const i = Number(m[1])
    const node = snap.children?.[i]
    return node?.boundingBox ?? null
  }

  return null
}

/** Read the selected node's bounding box, or null for malformed keys / missing nodes. */
function selectedNodeBoundingBox(snap: SnapView): AxBoundingBox | null {
  return boundingBoxForKey(snap, snap.selected ?? DEFAULT_SELECTED)
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

function buildAnnotatorEvents(rawEvents: RecordedMouseEvent[]): AnnotatorEvent[] {
  if (rawEvents.length === 0) {
    throw new Error('Recording has no events.')
  }

  const startEvent = rawEvents.find((event) => event.eventType === 'recording_start')
  if (!startEvent) {
    throw new Error('Failed to load startTime of video.')
  }

  const startTimeMs = Number(startEvent.timeUtcMs)

  return rawEvents
    .map((evt, idx) => ({ evt, idx }))
    .filter(({ evt }) => evt.eventType !== 'recording_start')
    .map(({ evt, idx }) => ({
      eventName: evt.eventType,
      title: (evt.axAttributes as SnapView | undefined)?.title ?? evt.eventType,
      timestampMs: Number(evt.timeUtcMs) - startTimeMs,
      axAttributes: evt.axAttributes ?? {},
      x: evt.x,
      y: evt.y,
      rawEventIndex: idx
    }))
}

export default function Annotator(): React.JSX.Element {
  const navigate = useNavigate()
  const { recordingId, displayName, videoUrl, isLoaded, setLoadedRecording } = useRecordingStore()
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

  // Custom annotation / bbox editing state
  const [isEditingBbox, setIsEditingBbox] = useState(false)
  const dragHandleRef = useRef<'tl' | 'tr' | 'bl' | 'br' | null>(null)
  const dragOriginRef = useRef<{ clientX: number; clientY: number; bbox: AxBoundingBox } | null>(
    null
  )

  const resetLoadedRecordingState = useCallback((): void => {
    setEvents([])
    setRawEvents([])
    setDurationMs(120_000)
    setCurrentTimeMs(0)
    setVideoLayoutPx({ width: 0, height: 0 })
    setVideoNativePx({ width: 0, height: 0 })
    setActiveEventIdx(null)
    setExpandedEventIdx(null)
    setHasUnsavedChanges(false)
    setEventTooltip(null)
    setIsEditingBbox(false)
  }, [])

  const loadRecordingIntoEditor = useCallback(
    (payload: LoadedRecordingPayload): void => {
      const annotatorEvents = buildAnnotatorEvents(payload.events)
      setLoadedRecording({
        recordingId: payload.recordingId,
        displayName: payload.displayName,
        videoUrl: payload.videoUrl
      })
      resetLoadedRecordingState()
      setEvents(annotatorEvents)
      setRawEvents(payload.events)
    },
    [resetLoadedRecordingState, setLoadedRecording]
  )

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
  }, [videoUrl])

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
    setIsLoading(true)
    setError(null)

    try {
      const result = await window.api.pickRecording()
      if (result.ok) {
        loadRecordingIntoEditor(result.payload)
      } else if (result.error !== 'Dialog canceled') {
        setError(result.error)
      }
    } finally {
      setIsLoading(false)
    }
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
        loadRecordingIntoEditor(result.payload)
      } else {
        if (result.error !== 'Save canceled') {
          setError(result.error)
        }
      }

      setIsRecording(false)
    }

    setIsRecordingLoading(false)
  }

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

  const handleEventClick = useCallback(
    (timestampMs: number, idx: number): void => {
      seekToTime(timestampMs)
      setActiveEventIdx(idx)
    },
    [seekToTime]
  )

  const handleEventDoubleClick = useCallback(
    (timestampMs: number, idx: number): void => {
      seekToTime(timestampMs)
      setActiveEventIdx(idx)
      setExpandedEventIdx(idx)
      setIsEditingBbox(false)
    },
    [seekToTime]
  )

  const handleCollapseTree = useCallback((): void => {
    setExpandedEventIdx(null)
    setIsEditingBbox(false)
  }, [])

  /**
   * Write the new selection key onto the expanded event's snapshot and mirror it into
   * rawEvents for persistence. One field, one write — no clearing, no invariants to maintain.
   *
   * In custom-annotation edit mode, the overlay stays on `user_override`; clicking another
   * node copies that node's bbox into `userOverride` as a reference geometry to refine.
   */
  const selectNode = useCallback(
    (nodeKey: string): void => {
      if (expandedEventIdx === null || expandedEventIdx >= events.length) return

      const evt = events[expandedEventIdx]
      const snap = evt.axAttributes as SnapView | undefined
      if (!snap?.current) return

      if (isEditingBbox && nodeKey !== 'user_override') {
        const refBbox = boundingBoxForKey(snap, nodeKey)
        if (!refBbox) return

        const updatedSnap: SnapView = {
          ...snap,
          userOverride: { boundingBox: { ...refBbox } },
          selected: 'user_override'
        }
        const rawSnap = rawEvents[evt.rawEventIndex]?.axAttributes as SnapView | undefined
        if (rawSnap) {
          rawSnap.userOverride = { boundingBox: { ...refBbox } }
          rawSnap.selected = 'user_override'
        }

        setHasUnsavedChanges(true)
        setEvents((prev) =>
          prev.map((e, i) =>
            i === expandedEventIdx ? { ...e, axAttributes: updatedSnap as AxAttributesPayload } : e
          )
        )
        return
      }

      const updatedSnap = { ...snap, selected: nodeKey }
      const rawSnap = rawEvents[evt.rawEventIndex]?.axAttributes as SnapView | undefined
      if (rawSnap) rawSnap.selected = nodeKey

      setHasUnsavedChanges(true)
      setEvents((prev) =>
        prev.map((e, i) =>
          i === expandedEventIdx ? { ...e, axAttributes: updatedSnap as AxAttributesPayload } : e
        )
      )
    },
    [expandedEventIdx, events, rawEvents, isEditingBbox]
  )

  /**
   * Write a label field (title or description) onto the expanded event's snapshot and
   * mirror it into the rawEvents array so Save persists it.
   */
  const updateEventLabel = useCallback(
    (field: 'title' | 'description', value: string): void => {
      if (expandedEventIdx === null || expandedEventIdx >= events.length) return
      const evt = events[expandedEventIdx]
      const snap = evt.axAttributes as SnapView | undefined
      if (!snap) return

      // Empty string → clear back to null so the placeholder reappears and JSONL stays clean.
      const next = value.length === 0 ? null : value
      snap[field] = next

      const rawSnap = rawEvents[evt.rawEventIndex]?.axAttributes as SnapView | undefined
      if (rawSnap) rawSnap[field] = next

      setHasUnsavedChanges(true)
      // Force re-render — we mutated in place, React won't see it otherwise.
      // Also sync title onto the AnnotatorEvent view model so the sidebar stays current.
      setEvents((prev) =>
        prev.map((e, i) => {
          if (i !== expandedEventIdx || field !== 'title') return e
          return { ...e, title: next ?? e.eventName }
        })
      )
    },
    [expandedEventIdx, events, rawEvents]
  )

  const handleSave = useCallback(async (): Promise<void> => {
    if (!recordingId || rawEvents.length === 0) return
    const result = await window.api.saveRecordingEvents(recordingId, rawEvents)
    if (result.ok) {
      setHasUnsavedChanges(false)
    } else {
      setError(result.error)
    }
  }, [recordingId, rawEvents])

  const updateUserOverrideBbox = useCallback(
    (bbox: AxBoundingBox): void => {
      if (expandedEventIdx === null || expandedEventIdx >= events.length) return
      const evt = events[expandedEventIdx]
      const snap = evt.axAttributes as SnapView | undefined
      if (!snap) return

      const updatedSnap: SnapView = { ...snap, userOverride: { boundingBox: bbox } }
      const rawSnap = rawEvents[evt.rawEventIndex]?.axAttributes as SnapView | undefined
      if (rawSnap) rawSnap.userOverride = { boundingBox: bbox }

      setHasUnsavedChanges(true)
      setEvents((prev) =>
        prev.map((e, i) =>
          i === expandedEventIdx ? { ...e, axAttributes: updatedSnap as AxAttributesPayload } : e
        )
      )
    },
    [expandedEventIdx, events, rawEvents]
  )

  /**
   * Enter custom annotation edit mode. Preserves an existing userOverride bbox;
   * seeds a new 100×100 box centered on the event click (native px), clamped to the frame.
   */
  const handleStartCustomAnnotation = useCallback((): void => {
    if (expandedEventIdx === null || expandedEventIdx >= events.length) return
    const evt = events[expandedEventIdx]
    const snap = evt.axAttributes as SnapView | undefined
    if (!snap?.current) return

    if (!snap.userOverride) {
      const SIZE = 100
      const half = SIZE / 2
      const vw = videoNativePx.width
      const vh = videoNativePx.height

      let cx: number
      let cy: number
      if (evt.x !== undefined && evt.y !== undefined) {
        cx = evt.x
        cy = evt.y
      } else if (vw > 0 && vh > 0) {
        cx = vw / 2
        cy = vh / 2
      } else {
        cx = half
        cy = half
      }

      let x = cx - half
      let y = cy - half
      if (vw > 0 && vh > 0) {
        const maxX = Math.max(0, vw - SIZE)
        const maxY = Math.max(0, vh - SIZE)
        x = Math.max(0, Math.min(x, maxX))
        y = Math.max(0, Math.min(y, maxY))
      }

      const bbox: AxBoundingBox = { x, y, width: SIZE, height: SIZE }

      const updatedSnap: SnapView = {
        ...snap,
        userOverride: { boundingBox: bbox },
        selected: 'user_override'
      }
      const rawSnap = rawEvents[evt.rawEventIndex]?.axAttributes as SnapView | undefined
      if (rawSnap) {
        rawSnap.userOverride = { boundingBox: bbox }
        rawSnap.selected = 'user_override'
      }
      setHasUnsavedChanges(true)
      setEvents((prev) =>
        prev.map((e, i) =>
          i === expandedEventIdx ? { ...e, axAttributes: updatedSnap as AxAttributesPayload } : e
        )
      )
    } else {
      selectNode('user_override')
    }
    setIsEditingBbox(true)
  }, [expandedEventIdx, events, rawEvents, selectNode, videoNativePx])

  const scale = videoNativePx.width > 0 ? videoLayoutPx.width / videoNativePx.width : 1

  // Keep a ref so the drag mousemove handler always reads the current scale
  // without needing to be re-registered every time the video resizes.
  const scaleRef = useRef(scale)
  useEffect(() => {
    scaleRef.current = scale
  }, [scale])

  // Keep a ref so the drag handler always calls the latest updateUserOverrideBbox
  // closure (which captures the current events / expandedEventIdx) without
  // re-registering document listeners on every drag step.
  const updateBboxRef = useRef(updateUserOverrideBbox)
  useEffect(() => {
    updateBboxRef.current = updateUserOverrideBbox
  }, [updateUserOverrideBbox])

  useEffect(() => {
    if (!isEditingBbox) return

    const handleMouseMove = (e: MouseEvent): void => {
      if (!dragHandleRef.current || !dragOriginRef.current) return
      const handle = dragHandleRef.current
      const origin = dragOriginRef.current
      const dx = (e.clientX - origin.clientX) / scaleRef.current
      const dy = (e.clientY - origin.clientY) / scaleRef.current
      const orig = origin.bbox
      const MIN = 10
      const ox = orig.x
      const oy = orig.y
      const right = ox + orig.width
      const bottom = oy + orig.height

      let x: number
      let y: number
      let width: number
      let height: number

      if (handle === 'tl') {
        // Anchor: bottom-right — (right, bottom) fixed
        const nx = Math.min(ox + dx, right - MIN)
        const ny = Math.min(oy + dy, bottom - MIN)
        x = nx
        y = ny
        width = right - nx
        height = bottom - ny
      } else if (handle === 'tr') {
        // Anchor: bottom-left — (ox, bottom) fixed
        x = ox
        y = Math.min(oy + dy, bottom - MIN)
        width = Math.max(MIN, orig.width + dx)
        height = bottom - y
      } else if (handle === 'bl') {
        // Anchor: top-right — (right, oy) fixed
        x = Math.min(ox + dx, right - MIN)
        y = oy
        width = right - x
        height = Math.max(MIN, orig.height + dy)
      } else {
        // br — anchor: top-left — (ox, oy) fixed
        x = ox
        y = oy
        width = Math.max(MIN, orig.width + dx)
        height = Math.max(MIN, orig.height + dy)
      }

      updateBboxRef.current({ x, y, width, height })
    }

    const handleMouseUp = (): void => {
      dragHandleRef.current = null
      dragOriginRef.current = null
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isEditingBbox])

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
    const attrs = sortedEvents[displayEventIdx].axAttributes as SnapView | undefined
    if (!attrs?.current) return null
    return attrs as Required<Pick<SnapView, 'current' | 'parents' | 'children'>> & SnapView
  }, [displayEventIdx, sortedEvents])

  /** Current selection key, read directly from the snapshot (no separate UI state). */
  const activeNodeKey = activeSnapshot?.selected ?? DEFAULT_SELECTED

  const activeBbox: AxBoundingBox | null = useMemo(
    () => (activeSnapshot ? selectedNodeBoundingBox(activeSnapshot) : null),
    [activeSnapshot]
  )

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
            {displayName && (
              <span className="font-mono text-[0.7rem] uppercase tracking-[0.12em] text-[#8d91a0]">
                {displayName}
              </span>
            )}
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
          ) : videoUrl ? (
            <div>
              <div style={{ position: 'relative', display: 'inline-block' }}>
                <video
                  ref={videoRef}
                  src={videoUrl}
                  className="max-w-full max-h-full"
                  controls
                  onLoadedMetadata={handleLoadedMetadata}
                />
                {activeBbox && (
                  <>
                    <div
                      style={{
                        position: 'absolute',
                        left: activeBbox.x * scale,
                        top: activeBbox.y * scale,
                        width: activeBbox.width * scale,
                        height: activeBbox.height * scale,
                        border: isEditingBbox ? '2px dashed #ff3b30' : '2px solid #ff3b30',
                        backgroundColor: 'rgba(255, 59, 48, 0.15)',
                        borderRadius: 3,
                        pointerEvents: 'none'
                      }}
                    />
                    {isEditingBbox &&
                      (['tl', 'tr', 'bl', 'br'] as const).map((handle) => {
                        const isLeft = handle[1] === 'l'
                        const isTop = handle[0] === 't'
                        const cx = isLeft ? activeBbox.x : activeBbox.x + activeBbox.width
                        const cy = isTop ? activeBbox.y : activeBbox.y + activeBbox.height
                        return (
                          <div
                            key={handle}
                            onMouseDown={(e) => {
                              e.preventDefault()
                              dragHandleRef.current = handle
                              dragOriginRef.current = {
                                clientX: e.clientX,
                                clientY: e.clientY,
                                bbox: { ...activeBbox }
                              }
                            }}
                            style={{
                              position: 'absolute',
                              left: cx * scale - 5,
                              top: cy * scale - 5,
                              width: 10,
                              height: 10,
                              backgroundColor: '#ff3b30',
                              border: '1.5px solid white',
                              borderRadius: 2,
                              cursor:
                                handle === 'tl' || handle === 'br' ? 'nw-resize' : 'ne-resize',
                              zIndex: 10
                            }}
                          />
                        )
                      })}
                  </>
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
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <button
                  type="button"
                  onClick={
                    isEditingBbox ? () => setIsEditingBbox(false) : handleStartCustomAnnotation
                  }
                  className={`ann-btn ${isEditingBbox ? 'ann-btn-save' : 'ann-btn-secondary'}`}
                  style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
                >
                  {isEditingBbox ? 'Done' : 'Custom Annotation'}
                </button>
                <span className="ann-sidebar-count">
                  {formatTimestamp(sortedEvents[expandedEventIdx].timestampMs)}
                </span>
              </div>
            </div>
            <div className="ann-sidebar-list">
              {/* Event-level label (title + description) */}
              <div className="ax-tree-section">
                <div className="ax-tree-section-label">Label</div>
                <input
                  type="text"
                  className="ann-label-input"
                  value={(activeSnapshot.title as string | null | undefined) ?? ''}
                  placeholder={sortedEvents[expandedEventIdx].eventName}
                  onChange={(e) => updateEventLabel('title', e.target.value)}
                  aria-label="Event title"
                />
                <textarea
                  className="ann-label-textarea"
                  value={(activeSnapshot.description as string | null | undefined) ?? ''}
                  placeholder={(() => {
                    const e = sortedEvents[expandedEventIdx]
                    return e.x !== undefined && e.y !== undefined
                      ? `(${Math.round(e.x)}, ${Math.round(e.y)})`
                      : 'description'
                  })()}
                  onChange={(e) => updateEventLabel('description', e.target.value)}
                  rows={2}
                  aria-label="Event description"
                />
              </div>

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
                    const key = `parents:${i}`
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

              {/* User-authored override — shown only if one exists for this event. */}
              {activeSnapshot.userOverride && (
                <div className="ax-tree-section">
                  <div className="ax-tree-section-label">Override</div>
                  <div
                    className={`ax-tree-node ${activeNodeKey === 'user_override' ? 'ax-tree-node-active' : ''}`}
                    onClick={() => selectNode('user_override')}
                  >
                    <span className="ax-tree-node-role">custom</span>
                    <span className="ax-tree-node-text">user-drawn region</span>
                    <span className="ax-tree-node-bbox">bbox</span>
                  </div>
                </div>
              )}

              {/* Children */}
              {activeSnapshot.children.length > 0 && (
                <div className="ax-tree-section">
                  <div className="ax-tree-section-label">
                    Children ({activeSnapshot.children.length})
                  </div>
                  {activeSnapshot.children.map((node, i) => {
                    const key = `children:${i}`
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
                        <span className="ann-event-name">{evt.title}</span>
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
