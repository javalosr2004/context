import type {
  AxAttributes,
  AxAttributesPayload,
  AxBoundingBox,
  RecordedMouseEvent
} from '../../../../shared/types'
import type { AnnotatorEvent, SnapView } from './types'

export const DEFAULT_SELECTED = 'current'

const PARENTS_KEY = /^parents:(\d+)$/
const CHILDREN_KEY = /^children:(\d+)$/

export function isSnapView(
  payload: AxAttributesPayload | null | undefined
): payload is AxAttributesPayload & SnapView {
  if (!payload || typeof payload !== 'object') {
    return false
  }

  return 'current' in payload && 'parents' in payload && 'children' in payload
}

export function buildAnnotatorEvents(rawEvents: RecordedMouseEvent[]): AnnotatorEvent[] {
  if (rawEvents.length === 0) {
    throw new Error('Recording has no events.')
  }

  const startEvent = rawEvents.find((event) => event.eventType === 'recording_start')
  if (!startEvent) {
    throw new Error('Failed to load startTime of video.')
  }

  const startTimeMs = Number(startEvent.timeUtcMs)

  return rawEvents
    .map((event, index) => ({ event, index }))
    .filter(({ event }) => event.eventType !== 'recording_start')
    .map(({ event, index }) => {
      const snap = isSnapView(event.axAttributes) ? event.axAttributes : null
      return {
        eventName: event.eventType,
        title: snap?.title ?? event.eventType,
        timestampMs: Number(event.timeUtcMs) - startTimeMs,
        axAttributes: event.axAttributes ?? {},
        x: event.x,
        y: event.y,
        rawEventIndex: index
      }
    })
}

export function boundingBoxForSelection(snap: SnapView, selection: string): AxBoundingBox | null {
  const key = selection || DEFAULT_SELECTED

  if (key === 'current') {
    return snap.current?.boundingBox ?? null
  }

  if (key === 'user_override') {
    return snap.userOverride?.boundingBox ?? null
  }

  const parentMatch = PARENTS_KEY.exec(key)
  if (parentMatch) {
    const index = Number(parentMatch[1])
    return snap.parents?.[index]?.boundingBox ?? null
  }

  const childMatch = CHILDREN_KEY.exec(key)
  if (childMatch) {
    const index = Number(childMatch[1])
    return snap.children?.[index]?.boundingBox ?? null
  }

  return null
}

export function selectedBoundingBox(snap: SnapView): AxBoundingBox | null {
  return boundingBoxForSelection(snap, snap.selected ?? DEFAULT_SELECTED)
}

export function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

export function nodeLabel(node: AxAttributes): string {
  return (
    node.axTitle || node.axValue || node.axDescription || node.axRoleDescription || 'unnamed node'
  )
}
