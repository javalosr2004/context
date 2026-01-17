import { ElectronAPI } from '@electron-toolkit/preload'
import type { ScreenSource, MousePosition, Result } from '../shared/types'

interface Api {
  getSources: () => Promise<Result<ScreenSource[]>>
  getCursorDisplay: () => Promise<Result<Electron.Display>>
  onMousePosition: (callback: (position: MousePosition) => void) => () => void
  startMouseTracking: () => void
  stopMouseTracking: () => void
}

declare global {
  interface Window {
    electron: ElectronAPI
    api: Api
  }
}
