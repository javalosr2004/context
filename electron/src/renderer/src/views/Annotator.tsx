import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { useRecordingStore } from '../store/recordingStore'

export interface AnnotatorEvent {
  eventName: string
  timestampMs: number
  axAttributes: Record<string, string>
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
  const { archivePath, videoPath, isLoaded, setExtractedPaths, setArchivePath } =
    useRecordingStore()
  const [events, setEvents] = useState<AnnotatorEvent[]>([])
  const [durationMs, setDurationMs] = useState(120_000)
  const [currentTimeMs, setCurrentTimeMs] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const rafIdRef = useRef<number | null>(null)

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
      console.log('Loading recording.')
      setIsLoading(true)
      setError(null)

      try {
        const result = await window.api.importRecording(archivePath)
        if (result.ok) {
          const { videoPath, eventsPath, events: rawEvents } = result.payload

          // Transform Rust events to AnnotatorEvents with relative timestamps
          if (rawEvents.length > 0) {
            // Use recording_start event as baseline, fall back to first event
            console.log(rawEvents)
            const startEvent = rawEvents.find((e) => e.eventType === 'recording_start')
            if (!startEvent) {
              setError('Failed to load startTime of video.')
              setIsLoading(false)
              return
            }
            setExtractedPaths(videoPath, eventsPath)

            const startTimeMs = Number(startEvent?.timeUtcMs ?? rawEvents[0].timeUtcMs)

            // Filter out the synthetic recording_start event from display
            const annotatorEvents: AnnotatorEvent[] = rawEvents
              .filter((evt) => evt.eventType !== 'recording_start')
              .map((evt) => ({
                eventName: evt.eventType,
                timestampMs: Number(evt.timeUtcMs) - startTimeMs,
                axAttributes: evt.axAttributes
              }))
            setEvents(annotatorEvents)
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
      const video = videoRef.current
      console.log('video.videoWidth', video.videoWidth)
      console.log('video.videoHeight', video.videoHeight)
      console.log('video.clientWidth', video.clientWidth)
      console.log('video.clientHeight', video.clientHeight)
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

  const handleEventClick = useCallback(
    (timestampMs: number): void => {
      seekToTime(timestampMs)
    },
    [seekToTime]
  )

  const sortedEvents = useMemo(
    () => [...events].sort((a, b) => a.timestampMs - b.timestampMs),
    [events]
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
            <video
              ref={videoRef}
              src={`media://local/${encodeURIComponent(videoPath)}`}
              className="max-w-full max-h-full"
              controls
              onLoadedMetadata={handleLoadedMetadata}
            />
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
                  className="ann-timeline-marker"
                  style={{ left: `${positionPercent}%` }}
                  title={`${evt.eventName} at ${formatTimestamp(evt.timestampMs)}`}
                />
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
                  onClick={() => handleEventClick(evt.timestampMs)}
                  className={`ann-event ${
                    evt.timestampMs <= currentTimeMs ? 'ann-event-past' : ''
                  }`}
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
      </aside>
    </div>
  )
}
