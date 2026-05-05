import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Dispatch, MouseEvent as ReactMouseEvent, SetStateAction } from 'react'
import type { AxAttributesPayload, RecordedMouseEvent } from '../../../../shared/types'
import type { AxBoundingBox } from './types'
import { boundingBoxForSelection, isSnapView } from './model'
import type {
  AnnotatorEvent,
  BboxTransform,
  DragHandle,
  LabelField,
  SnapView,
  VideoDimensions
} from './types'

interface UseAnnotationEditorOptions {
  recordingId: string | null
  setEvents: Dispatch<SetStateAction<AnnotatorEvent[]>>
  rawEvents: RecordedMouseEvent[]
  setRawEvents: Dispatch<SetStateAction<RecordedMouseEvent[]>>
  sortedEvents: AnnotatorEvent[]
  expandedEventIdx: number | null
  videoNativePx: VideoDimensions
  transform: BboxTransform
  onError: (error: string) => void
}

interface UseAnnotationEditorResult {
  hasUnsavedChanges: boolean
  isEditingBbox: boolean
  activeSnapshot: SnapView | null
  resetEditorState: () => void
  stopEditingBbox: () => void
  selectNode: (nodeKey: string) => void
  updateEventLabel: (field: LabelField, value: string) => void
  updateUserOverrideBbox: (bbox: AxBoundingBox) => void
  handleStartCustomAnnotation: () => void
  beginBboxResize: (handle: DragHandle, pointerEvent: ReactMouseEvent, bbox: AxBoundingBox) => void
  save: () => Promise<void>
}

export function useAnnotationEditor({
  recordingId,
  setEvents,
  rawEvents,
  setRawEvents,
  sortedEvents,
  expandedEventIdx,
  videoNativePx,
  transform,
  onError
}: UseAnnotationEditorOptions): UseAnnotationEditorResult {
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [isEditingBbox, setIsEditingBbox] = useState(false)
  const dragHandleRef = useRef<DragHandle | null>(null)
  const dragOriginRef = useRef<{ clientX: number; clientY: number; bbox: AxBoundingBox } | null>(
    null
  )
  const transformRef = useRef(transform)

  const expandedEvent = useMemo(() => {
    if (expandedEventIdx === null || expandedEventIdx >= sortedEvents.length) {
      return null
    }

    return sortedEvents[expandedEventIdx]
  }, [expandedEventIdx, sortedEvents])

  const activeSnapshot = useMemo(() => {
    if (
      !expandedEvent ||
      !isSnapView(expandedEvent.axAttributes) ||
      !expandedEvent.axAttributes.current
    ) {
      return null
    }

    return expandedEvent.axAttributes
  }, [expandedEvent])

  const resetEditorState = useCallback((): void => {
    setHasUnsavedChanges(false)
    setIsEditingBbox(false)
  }, [])

  useEffect(() => {
    transformRef.current = transform
  }, [transform])

  const applySnapshotUpdate = useCallback(
    (transform: (snapshot: SnapView, event: AnnotatorEvent) => SnapView | null): void => {
      if (!expandedEvent) {
        return
      }

      const rawEvent = rawEvents[expandedEvent.rawEventIndex]
      const snapshot = isSnapView(rawEvent?.axAttributes)
        ? rawEvent.axAttributes
        : isSnapView(expandedEvent.axAttributes)
          ? expandedEvent.axAttributes
          : null

      if (!snapshot) {
        return
      }

      const nextSnapshot = transform(snapshot, expandedEvent)
      if (!nextSnapshot) {
        return
      }

      setHasUnsavedChanges(true)
      setRawEvents((previous) =>
        previous.map((event, index) =>
          index === expandedEvent.rawEventIndex
            ? { ...event, axAttributes: nextSnapshot as AxAttributesPayload }
            : event
        )
      )
      setEvents((previous) =>
        previous.map((event) =>
          event.rawEventIndex === expandedEvent.rawEventIndex
            ? {
                ...event,
                axAttributes: nextSnapshot as AxAttributesPayload,
                title: nextSnapshot.title ?? event.eventName
              }
            : event
        )
      )
    },
    [expandedEvent, rawEvents, setEvents, setRawEvents]
  )

  const selectNode = useCallback(
    (nodeKey: string): void => {
      if (!activeSnapshot?.current) {
        return
      }

      if (isEditingBbox && nodeKey !== 'user_override') {
        const referenceBbox = boundingBoxForSelection(activeSnapshot, nodeKey)
        if (!referenceBbox) {
          return
        }

        applySnapshotUpdate((snapshot) => ({
          ...snapshot,
          userOverride: { boundingBox: { ...referenceBbox } },
          selected: 'user_override'
        }))
        return
      }

      applySnapshotUpdate((snapshot) => ({ ...snapshot, selected: nodeKey }))
    },
    [activeSnapshot, applySnapshotUpdate, isEditingBbox]
  )

  const updateEventLabel = useCallback(
    (field: LabelField, value: string): void => {
      const nextValue = value.length === 0 ? null : value
      applySnapshotUpdate((snapshot) => ({ ...snapshot, [field]: nextValue }))
    },
    [applySnapshotUpdate]
  )

  const updateUserOverrideBbox = useCallback(
    (bbox: AxBoundingBox): void => {
      applySnapshotUpdate((snapshot) => ({
        ...snapshot,
        userOverride: { boundingBox: { ...bbox } }
      }))
    },
    [applySnapshotUpdate]
  )

  const handleStartCustomAnnotation = useCallback((): void => {
    if (!expandedEvent || !activeSnapshot?.current) {
      return
    }

    if (activeSnapshot.userOverride) {
      selectNode('user_override')
      setIsEditingBbox(true)
      return
    }

    const size = 100
    const half = size / 2
    const width = videoNativePx.width
    const height = videoNativePx.height

    const centerX = expandedEvent.x ?? (width > 0 ? width / 2 : half)
    const centerY = expandedEvent.y ?? (height > 0 ? height / 2 : half)

    let x = centerX - half
    let y = centerY - half

    if (width > 0 && height > 0) {
      x = Math.max(0, Math.min(x, Math.max(0, width - size)))
      y = Math.max(0, Math.min(y, Math.max(0, height - size)))
    }

    applySnapshotUpdate((snapshot) => ({
      ...snapshot,
      userOverride: { boundingBox: { x, y, width: size, height: size } },
      selected: 'user_override'
    }))
    setIsEditingBbox(true)
  }, [activeSnapshot, applySnapshotUpdate, expandedEvent, selectNode, videoNativePx])

  const beginBboxResize = useCallback(
    (handle: DragHandle, pointerEvent: ReactMouseEvent, bbox: AxBoundingBox): void => {
      pointerEvent.preventDefault()
      dragHandleRef.current = handle
      dragOriginRef.current = {
        clientX: pointerEvent.clientX,
        clientY: pointerEvent.clientY,
        bbox: { ...bbox }
      }
    },
    []
  )

  useEffect(() => {
    if (!isEditingBbox) {
      return
    }

    const handleMouseMove = (event: MouseEvent): void => {
      if (!dragHandleRef.current || !dragOriginRef.current) {
        return
      }

      const min = 10
      const origin = dragOriginRef.current
      const { scaleX, scaleY } = transformRef.current
      const dx = scaleX !== 0 ? (event.clientX - origin.clientX) / scaleX : 0
      const dy = scaleY !== 0 ? (event.clientY - origin.clientY) / scaleY : 0
      const original = origin.bbox
      const right = original.x + original.width
      const bottom = original.y + original.height

      let x = original.x
      let y = original.y
      let width = original.width
      let height = original.height

      switch (dragHandleRef.current) {
        case 'tl':
          x = Math.min(original.x + dx, right - min)
          y = Math.min(original.y + dy, bottom - min)
          width = right - x
          height = bottom - y
          break
        case 'tr':
          y = Math.min(original.y + dy, bottom - min)
          width = Math.max(min, original.width + dx)
          height = bottom - y
          break
        case 'bl':
          x = Math.min(original.x + dx, right - min)
          width = right - x
          height = Math.max(min, original.height + dy)
          break
        case 'br':
          width = Math.max(min, original.width + dx)
          height = Math.max(min, original.height + dy)
          break
      }

      updateUserOverrideBbox({ x, y, width, height })
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
  }, [isEditingBbox, updateUserOverrideBbox])

  const save = useCallback(async (): Promise<void> => {
    if (!recordingId || rawEvents.length === 0) {
      return
    }

    const result = await window.api.saveRecordingEvents(recordingId, rawEvents)
    if (result.ok) {
      setHasUnsavedChanges(false)
      return
    }

    onError(result.error)
  }, [onError, rawEvents, recordingId])

  return {
    hasUnsavedChanges,
    isEditingBbox,
    activeSnapshot,
    resetEditorState,
    stopEditingBbox: () => setIsEditingBbox(false),
    selectNode,
    updateEventLabel,
    updateUserOverrideBbox,
    handleStartCustomAnnotation,
    beginBboxResize,
    save
  }
}
