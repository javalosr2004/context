import { ElectronAPI } from '@electron-toolkit/preload'
import type { ScreenSource, MousePosition, MouseClick, Result, RecordedMouseEvent } from '../shared/types'

interface Api {
  getSources: () => Promise<Result<ScreenSource[]>>
  getCursorDisplay: () => Promise<Result<Electron.Display>>
  onMousePosition: (callback: (position: MousePosition) => void) => () => void
  onMouseClick: (callback: (click: MouseClick) => void) => () => void
  startRecording: () => Promise<Result<{ tempPath: string }>>
  pushRecordingChunk: (chunk: ArrayBuffer) => Promise<Result<null>>
  finishRecording: (defaultName: string) => Promise<Result<{ zipPath: string }>>
  importRecording: (
    archivePath: string
  ) => Promise<Result<{ videoPath: string; eventsPath: string; events: RecordedMouseEvent[] }>>
  showOpenRecordingDialog: () => Promise<Result<{ filePath: string }>>
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
