import { ElectronAPI } from '@electron-toolkit/preload'
import type {
  LoadedRecordingPayload,
  MousePosition,
  RecordedMouseEvent,
  Result,
  ScreenSource
} from '../shared/types'

interface Api {
  getSources: () => Promise<Result<ScreenSource[]>>
  getCursorDisplay: () => Promise<Result<Electron.Display>>
  onMousePosition: (callback: (position: MousePosition) => void) => () => void
  startRecording: () => Promise<Result<null>>
  pushRecordingChunk: (chunk: ArrayBuffer) => Promise<Result<null>>
  finishRecording: (defaultName: string) => Promise<Result<LoadedRecordingPayload>>
  pickRecording: () => Promise<Result<LoadedRecordingPayload>>
  saveRecordingEvents: (recordingId: string, events: RecordedMouseEvent[]) => Promise<Result<null>>
  openViewer: () => Promise<Result<null>>
  closeViewer: () => Promise<Result<null>>
  sendViewerData: (data: unknown) => Promise<Result<null>>
  onViewerData: (callback: (data: unknown) => void) => () => void
}

declare global {
  interface Window {
    electron: ElectronAPI
    api: Api
  }
}
