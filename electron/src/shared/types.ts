import type {
  AxSnapshot,
  MouseEvent as RustMouseEvent
} from '../../resources/types/rust_types'

// Re-export Rust-generated types
export type {
  AxAttributes,
  AxBoundingBox,
  AxSnapshot,
  CapturedMouseEvent as RustCapturedMouseEvent,
  GetMouseEventsResult,
  MouseEvent,
  RpcErrorResult,
  StatusResult,
  UserOverride
} from '../../resources/types/rust_types'

/** Legacy JSONL: flat unprefixed + `parent_{n}_*` / `child_{n}_*` string keys. */
export type AxAttributeMap = Record<string, string>

/** New recordings: structured snapshot; older `.ctx` files may still use `AxAttributeMap`. */
export type AxAttributesPayload = AxSnapshot | AxAttributeMap

export type RecordedMouseEvent = RustMouseEvent & {
  axAttributes?: AxAttributesPayload | null
}

export type Result<T> = { ok: true; payload: T } | { ok: false; error: string }

export const Ok = <T>(payload: T): Result<T> => ({ ok: true, payload })
export const Err = <T>(error: string): Result<T> => ({ ok: false, error })

export interface ScreenSource {
  id: string
  name: string
  displayId: string
  thumbnail: string
}

export interface MousePosition {
  x: number
  y: number
}
