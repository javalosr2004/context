import type { JSX, MouseEvent as ReactMouseEvent, RefObject } from 'react'
import type { AxBoundingBox } from './types'
import type { AnnotatorEvent, DragHandle, VideoDimensions } from './types'

interface AnnotatorVideoPaneProps {
  isLoading: boolean
  error: string | null
  videoUrl: string | null
  videoRef: RefObject<HTMLVideoElement | null>
  activeBbox: AxBoundingBox | null
  currentTimeMs: number
  durationMs: number
  sortedEvents: AnnotatorEvent[]
  scale: number
  isEditingBbox: boolean
  videoNativePx: VideoDimensions
  videoLayoutPx: VideoDimensions
  formatTimestamp: (ms: number) => string
  onLoadedMetadata: () => void
  onImport: () => Promise<void>
  onTimelineClick: (event: ReactMouseEvent<HTMLDivElement>) => void
  onEventHoverEnter: (event: AnnotatorEvent, pointerEvent: ReactMouseEvent) => void
  onEventHoverMove: (pointerEvent: ReactMouseEvent) => void
  onEventHoverLeave: () => void
  onBboxHandleMouseDown: (
    handle: DragHandle,
    pointerEvent: ReactMouseEvent,
    bbox: AxBoundingBox
  ) => void
}

const BBOX_HANDLES: DragHandle[] = ['tl', 'tr', 'bl', 'br']

export function AnnotatorVideoPane({
  isLoading,
  error,
  videoUrl,
  videoRef,
  activeBbox,
  currentTimeMs,
  durationMs,
  sortedEvents,
  scale,
  isEditingBbox,
  videoNativePx,
  videoLayoutPx,
  formatTimestamp,
  onLoadedMetadata,
  onImport,
  onTimelineClick,
  onEventHoverEnter,
  onEventHoverMove,
  onEventHoverLeave,
  onBboxHandleMouseDown
}: AnnotatorVideoPaneProps): JSX.Element {
  return (
    <div className="ann-main">
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
                onLoadedMetadata={onLoadedMetadata}
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
                    BBOX_HANDLES.map((handle) => {
                      const isLeft = handle[1] === 'l'
                      const isTop = handle[0] === 't'
                      const x = isLeft ? activeBbox.x : activeBbox.x + activeBbox.width
                      const y = isTop ? activeBbox.y : activeBbox.y + activeBbox.height

                      return (
                        <div
                          key={handle}
                          onMouseDown={(event) => onBboxHandleMouseDown(handle, event, activeBbox)}
                          style={{
                            position: 'absolute',
                            left: x * scale - 5,
                            top: y * scale - 5,
                            width: 10,
                            height: 10,
                            backgroundColor: '#ff3b30',
                            border: '1.5px solid white',
                            borderRadius: 2,
                            cursor: handle === 'tl' || handle === 'br' ? 'nw-resize' : 'ne-resize',
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
              onClick={onImport}
              disabled={isLoading}
              className="ann-btn ann-btn-primary"
            >
              Import .ctx file
            </button>
          </div>
        )}
      </div>

      <div
        role="slider"
        aria-label="Video timeline"
        aria-valuemin={0}
        aria-valuemax={durationMs}
        aria-valuenow={currentTimeMs}
        tabIndex={0}
        onClick={onTimelineClick}
        className="ann-timeline"
      >
        <div
          className="ann-timeline-fill"
          style={{
            width: durationMs > 0 ? `${(currentTimeMs / durationMs) * 100}%` : '0%'
          }}
        />
        {durationMs > 0 &&
          sortedEvents.map((event, index) => {
            const left = Math.min(100, Math.max(0, (event.timestampMs / durationMs) * 100))
            return (
              <div
                key={`${event.timestampMs}-${index}`}
                className="ann-timeline-marker-hit"
                style={{ left: `${left}%` }}
                onMouseEnter={(pointerEvent) => onEventHoverEnter(event, pointerEvent)}
                onMouseMove={onEventHoverMove}
                onMouseLeave={onEventHoverLeave}
              >
                <div className="ann-timeline-marker" aria-hidden />
              </div>
            )
          })}
        {durationMs > 0 && (
          <div
            className="ann-timeline-playhead"
            style={{ left: `${(currentTimeMs / durationMs) * 100}%` }}
          />
        )}
        <div className="ann-timeline-time">
          {formatTimestamp(currentTimeMs)} / {formatTimestamp(durationMs)}
        </div>
      </div>
    </div>
  )
}
