import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'

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

const api = {
  startCapture: (fps?: number): Promise<CaptureResult> => ipcRenderer.invoke('capture:start', fps),
  stopCapture: (): Promise<CaptureResult> => ipcRenderer.invoke('capture:stop'),
  getCaptureStatus: (): Promise<CaptureStatus> => ipcRenderer.invoke('capture:status'),
  getGoStatus: (): Promise<GoStatus | null> => ipcRenderer.invoke('capture:go-status'),
  onCaptureStatus: (callback: (status: CaptureStatus) => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent, status: CaptureStatus): void => {
      callback(status)
    }
    ipcRenderer.on('capture:status', handler)
    return (): void => {
      ipcRenderer.removeListener('capture:status', handler)
    }
  }
}

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', electronAPI)
    contextBridge.exposeInMainWorld('api', api)
  } catch (error) {
    console.error(error)
  }
} else {
  // @ts-ignore
  window.electron = electronAPI
  // @ts-ignore
  window.api = api
}
