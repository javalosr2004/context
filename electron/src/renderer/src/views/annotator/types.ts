import type {
  AxAttributes,
  AxAttributesPayload,
  AxBoundingBox,
  RecordedMouseEvent,
  UserOverride
} from '../../../../shared/types'

export interface AnnotatorEvent {
  eventName: string
  title: string
  timestampMs: number
  axAttributes: AxAttributesPayload
  x?: number
  y?: number
  rawEventIndex: number
}

export type SnapView = {
  current?: AxAttributes
  parents?: AxAttributes[]
  children?: AxAttributes[]
  userOverride?: UserOverride | null
  selected?: string
  title?: string | null
  description?: string | null
}

export interface AnnotatorRecordingLoad {
  recordingId: string
  displayName: string
  videoUrl: string
  events: AnnotatorEvent[]
  rawEvents: RecordedMouseEvent[]
}

export interface VideoDimensions {
  width: number
  height: number
}

export interface EventTooltipState {
  x: number
  y: number
  left: number
  top: number
}

export type DragHandle = 'tl' | 'tr' | 'bl' | 'br'

export type LabelField = 'title' | 'description'

export type { AxBoundingBox }
