import type { MouseEvent as RustMouseEvent } from '../../resources/types/rust_types'

// Re-export Rust-generated types
export type {
  CapturedMouseEvent as RustCapturedMouseEvent,
  GetMouseEventsResult,
  MouseEvent,
  RpcErrorResult,
  StatusResult
} from '../../resources/types/rust_types'

export type RecordedMouseEvent = RustMouseEvent & {
  axAttributes?: Record<string, string> | null
}

/**
 * Generic result type for IPC responses.
 * Use discriminated union so TypeScript narrows correctly.
 */
export type Result<T> = { ok: true; payload: T } | { ok: false; error: string }

/**
 * Shorthand constructors for Result type
 */
export const Ok = <T>(payload: T): Result<T> => ({ ok: true, payload })
export const Err = <T>(error: string): Result<T> => ({ ok: false, error })

/**
 * Screen source information from desktopCapturer
 */
export interface ScreenSource {
  id: string
  name: string
  displayId: string
  thumbnail: string
}

/**
 * Mouse position coordinates
 */
export interface MousePosition {
  x: number
  y: number
}

/**
 * Mouse click event data
 */
export interface MouseClick {
  x: number
  y: number
  button: 'left' | 'right' | 'middle'
  timestamp: number // ms since UTC epoch
}
