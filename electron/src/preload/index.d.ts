import { ElectronAPI } from '@electron-toolkit/preload'

interface Api {
  rustInvoke: (method: string, params?: unknown) => Promise<unknown>
}

declare global {
  interface Window {
    electron: ElectronAPI
    api: Api
  }
}
