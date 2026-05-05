import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import type { DisplayInfo, RecordedMouseEvent } from '../../../shared/types'
import { useRecordingStore } from '../store/recordingStore'
import { AnnotatorSidebar } from './annotator/AnnotatorSidebar'
import { AnnotatorToolbar } from './annotator/AnnotatorToolbar'
import { AnnotatorVideoPane } from './annotator/AnnotatorVideoPane'
import { EventTooltip } from './annotator/EventTooltip'
import {
  DEFAULT_SELECTED,
  computeBboxTransform,
  extractDisplayInfo,
  isSnapView,
  selectedBoundingBox
} from './annotator/model'
import type { AnnotatorEvent, VideoDimensions } from './annotator/types'
import { useAnnotationEditor } from './annotator/useAnnotationEditor'
import { useAnnotatorRecording } from './annotator/useAnnotatorRecording'
import { useAnnotatorTimeline } from './annotator/useAnnotatorTimeline'

const EMPTY_VIDEO_DIMENSIONS: VideoDimensions = { width: 0, height: 0 }

export default function Annotator(): React.JSX.Element {
  const navigate = useNavigate()
  const { recordingId, displayName, videoUrl, isLoaded, setLoadedRecording } = useRecordingStore()
  const [events, setEvents] = useState<AnnotatorEvent[]>([])
  const [rawEvents, setRawEvents] = useState<RecordedMouseEvent[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [videoLayoutPx, setVideoLayoutPx] = useState<VideoDimensions>(EMPTY_VIDEO_DIMENSIONS)
  const [videoNativePx, setVideoNativePx] = useState<VideoDimensions>(EMPTY_VIDEO_DIMENSIONS)
  const [displayPx, setDisplayPx] = useState<DisplayInfo | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)

  const timeline = useAnnotatorTimeline({ events, videoRef })

  const transform = useMemo(
    () => computeBboxTransform({ displayPx, videoNativePx, videoLayoutPx }),
    [displayPx, videoNativePx, videoLayoutPx]
  )

  const annotationEditor = useAnnotationEditor({
    recordingId,
    setEvents,
    rawEvents,
    setRawEvents,
    sortedEvents: timeline.sortedEvents,
    expandedEventIdx: timeline.expandedEventIdx,
    videoNativePx,
    transform,
    onError: setError
  })

  const handleRecordingLoaded = useCallback(
    ({
      recordingId: nextRecordingId,
      displayName: nextDisplayName,
      videoUrl: nextVideoUrl,
      events: nextEvents,
      rawEvents: nextRawEvents
    }: {
      recordingId: string
      displayName: string
      videoUrl: string
      events: AnnotatorEvent[]
      rawEvents: RecordedMouseEvent[]
    }): void => {
      setLoadedRecording({
        recordingId: nextRecordingId,
        displayName: nextDisplayName,
        videoUrl: nextVideoUrl
      })
      setEvents(nextEvents)
      setRawEvents(nextRawEvents)
      setDisplayPx(extractDisplayInfo(nextRawEvents))
      setVideoLayoutPx(EMPTY_VIDEO_DIMENSIONS)
      setVideoNativePx(EMPTY_VIDEO_DIMENSIONS)
      timeline.resetTimelineState()
      annotationEditor.resetEditorState()
      setError(null)
    },
    [annotationEditor, setLoadedRecording, timeline]
  )

  const recording = useAnnotatorRecording({
    onLoad: handleRecordingLoaded,
    onError: setError,
    onLoadingChange: setIsLoading
  })

  useEffect(() => {
    const video = videoRef.current
    if (!video) {
      return
    }

    const observer = new ResizeObserver(() => {
      const rect = video.getBoundingClientRect()
      setVideoLayoutPx({
        width: Math.round(rect.width),
        height: Math.round(rect.height)
      })
    })

    observer.observe(video)
    return () => observer.disconnect()
  }, [videoUrl])

  const handleLoadedMetadata = useCallback((): void => {
    timeline.handleLoadedMetadata()
    if (!videoRef.current) {
      return
    }

    setVideoNativePx({
      width: videoRef.current.videoWidth,
      height: videoRef.current.videoHeight
    })
  }, [timeline])

  const displaySnapshot = useMemo(() => {
    if (
      timeline.displayEventIdx === null ||
      timeline.displayEventIdx >= timeline.sortedEvents.length
    ) {
      return null
    }

    const event = timeline.sortedEvents[timeline.displayEventIdx]
    if (!isSnapView(event.axAttributes) || !event.axAttributes.current) {
      return null
    }

    return event.axAttributes
  }, [timeline.displayEventIdx, timeline.sortedEvents])

  const activeBbox = useMemo(
    () => (displaySnapshot ? selectedBoundingBox(displaySnapshot) : null),
    [displaySnapshot]
  )

  const sidebarNodeKey = annotationEditor.activeSnapshot?.selected ?? DEFAULT_SELECTED

  return (
    <div className="ann">
      <div className="dash-grain" aria-hidden="true" />

      <AnnotatorToolbar
        displayName={displayName}
        isLoaded={isLoaded}
        isLoading={isLoading}
        isRecording={recording.isRecording}
        isRecordingLoading={recording.isRecordingLoading}
        hasUnsavedChanges={annotationEditor.hasUnsavedChanges}
        onBack={() => navigate('/')}
        onStartOrStopRecording={recording.startOrStopRecording}
        onImport={recording.importRecording}
        onSave={annotationEditor.save}
      />

      <div className="ann-body">
        <AnnotatorVideoPane
          isLoading={isLoading}
          error={error}
          videoUrl={videoUrl}
          videoRef={videoRef}
          activeBbox={activeBbox}
          currentTimeMs={timeline.currentTimeMs}
          durationMs={timeline.durationMs}
          sortedEvents={timeline.sortedEvents}
          transform={transform}
          isEditingBbox={annotationEditor.isEditingBbox}
          videoNativePx={videoNativePx}
          videoLayoutPx={videoLayoutPx}
          formatTimestamp={timeline.formatTimestamp}
          onLoadedMetadata={handleLoadedMetadata}
          onImport={recording.importRecording}
          onTimelineClick={timeline.handleTimelineClick}
          onEventHoverEnter={timeline.handleEventHoverEnter}
          onEventHoverMove={timeline.handleEventHoverMove}
          onEventHoverLeave={timeline.handleEventHoverLeave}
          onBboxHandleMouseDown={annotationEditor.beginBboxResize}
        />

        <AnnotatorSidebar
          sortedEvents={timeline.sortedEvents}
          currentTimeMs={timeline.currentTimeMs}
          activeEventIdx={timeline.activeEventIdx}
          expandedEventIdx={timeline.expandedEventIdx}
          activeSnapshot={annotationEditor.activeSnapshot}
          activeNodeKey={sidebarNodeKey}
          isEditingBbox={annotationEditor.isEditingBbox}
          formatTimestamp={timeline.formatTimestamp}
          onCollapseTree={timeline.handleCollapseTree}
          onStopEditingBbox={annotationEditor.stopEditingBbox}
          onStartCustomAnnotation={annotationEditor.handleStartCustomAnnotation}
          onSelectNode={annotationEditor.selectNode}
          onUpdateLabel={annotationEditor.updateEventLabel}
          onEventClick={timeline.handleEventClick}
          onEventDoubleClick={(timestampMs, index) => {
            annotationEditor.stopEditingBbox()
            timeline.handleEventDoubleClick(timestampMs, index)
          }}
          onEventHoverEnter={timeline.handleEventHoverEnter}
          onEventHoverMove={timeline.handleEventHoverMove}
          onEventHoverLeave={timeline.handleEventHoverLeave}
        />
      </div>

      <EventTooltip tooltip={timeline.eventTooltip} />
    </div>
  )
}
