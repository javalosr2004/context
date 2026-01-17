import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'
import type { ScreenSource, MousePosition, Result } from '../shared/types'

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
  startMouseTracking: (): void => ipcRenderer.send('start-mouse-tracking'),
  stopMouseTracking: (): void => ipcRenderer.send('stop-mouse-tracking')
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
