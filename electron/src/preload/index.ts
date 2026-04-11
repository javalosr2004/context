import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'
import type {
  ScreenSource,
  MousePosition,
  Result,
  RecordedMouseEvent
} from '../shared/types'

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
  startRecording: (): Promise<Result<{ tempPath: string }>> =>
    ipcRenderer.invoke('recording:start'),
  pushRecordingChunk: (chunk: ArrayBuffer): Promise<Result<null>> =>
    ipcRenderer.invoke('recording:push', chunk),
  finishRecording: (defaultName: string): Promise<Result<{ zipPath: string }>> =>
    ipcRenderer.invoke('recording:finish', defaultName),
  importRecording: (
    archivePath: string
  ): Promise<Result<{ videoPath: string; eventsPath: string; events: RecordedMouseEvent[] }>> =>
    ipcRenderer.invoke('recording:import', archivePath),
  showOpenRecordingDialog: (): Promise<Result<{ filePath: string }>> =>
    ipcRenderer.invoke('recording:show-open-dialog'),
  saveEvents: (eventsPath: string, archivePath: string, events: RecordedMouseEvent[]): Promise<Result<null>> =>
    ipcRenderer.invoke('recording:save-events', eventsPath, archivePath, events),

  // Viewer
  openViewer: (): Promise<Result<null>> => ipcRenderer.invoke('viewer:open'),
  closeViewer: (): Promise<Result<null>> => ipcRenderer.invoke('viewer:close'),
  sendViewerData: (data: unknown): Promise<Result<null>> =>
    ipcRenderer.invoke('viewer:send-data', data),
  onViewerData(callback: (data: unknown) => void): Unsubscribe {
    const handler = (_event: Electron.IpcRendererEvent, data: unknown): void => {
      callback(data)
    }
    ipcRenderer.on('viewer:data', handler)
    return () => {
      ipcRenderer.removeListener('viewer:data', handler)
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
