import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'
import type { ScreenSource, MousePosition, MouseClick, Result } from '../shared/types'

type Unsubscribe = () => void

const api = {
  getSources: (): Promise<Result<ScreenSource[]>> => ipcRenderer.invoke('get-sources'),
  getCursorDisplay: (): Promise<Result<Electron.Display>> =>
    ipcRenderer.invoke('get-cursor-display'),
  onMousePosition(callback: (position: MousePosition) => void): Unsubscribe {
    const handler = (_event: Electron.IpcRendererEvent, position: MousePosition): void => {
      callback(position)
    }
    ipcRenderer.on('mouse-position', handler)
    return () => {
      ipcRenderer.removeListener('mouse-position', handler)
    }
  },
  onMouseClick(callback: (click: MouseClick) => void): Unsubscribe {
    const handler = (_event: Electron.IpcRendererEvent, click: MouseClick): void => {
      callback(click)
    }
    ipcRenderer.on('mouse-click', handler)
    return () => {
      ipcRenderer.removeListener('mouse-click', handler)
    }
  },
  startMouseTracking: (): void => ipcRenderer.send('start-mouse-tracking'),
  stopMouseTracking: (): void => ipcRenderer.send('stop-mouse-tracking'),
  startMouseClickTracking: (): void => ipcRenderer.send('start-mouse-click-tracking'),
  stopMouseClickTracking: (): void => ipcRenderer.send('stop-mouse-click-tracking'),
  startRecording: (): Promise<Result<{ tempPath: string }>> =>
    ipcRenderer.invoke('recording:start'),
  pushRecordingChunk: (chunk: ArrayBuffer): Promise<Result<null>> =>
    ipcRenderer.invoke('recording:push', chunk),
  finishRecording: (defaultName: string): Promise<Result<{ filePath: string }>> =>
    ipcRenderer.invoke('recording:finish', defaultName)
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
