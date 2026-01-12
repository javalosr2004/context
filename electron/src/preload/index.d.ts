import { ElectronAPI } from '@electron-toolkit/preload'

export interface CaptureStatus {
  isRunning: boolean
  capturesDir: string
}

export interface GoStatus {
  running: boolean
  fps: number
  captureCount: number
  uptime: number
  outputDir: string
}

export interface CaptureResult {
  success: boolean
  status?: CaptureStatus
  error?: string
}

interface Api {
  startCapture: (fps?: number) => Promise<CaptureResult>
  stopCapture: () => Promise<CaptureResult>
  getCaptureStatus: () => Promise<CaptureStatus>
  getGoStatus: () => Promise<GoStatus | null>
  onCaptureStatus: (callback: (status: CaptureStatus) => void) => () => void
}

declare global {
  interface Window {
    electron: ElectronAPI
    api: Api
  }
}
