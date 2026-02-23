import { app, ipcMain, desktopCapturer, dialog, screen, protocol } from 'electron'
import { electronApp, optimizer } from '@electron-toolkit/utils'
import log from './logger'
import type { ScreenSource } from '../shared/types'
import { Result, Ok, Err } from '../shared/types'
import {
  startRecording,
  pushRecordingChunk,
  finishRecording,
  importRecording,
  getRecordingItems,
  readEventsFile,
  setMainWindow as setRecordingMainWindow
} from './recording'
import type { RecordedMouseEvent } from '../shared/types'
import { stopMouseTracking, setMainWindow as setMouseTrackingMainWindow } from './mouseTracking'
import { createWindow, createViewerWindow, getMainWindow, getViewerWindow } from './window'
import path from 'path'
import fs from 'node:fs'
import { Readable } from 'node:stream'

protocol.registerSchemesAsPrivileged([
  {
    scheme: 'media',
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      stream: true,
      bypassCSP: true
    }
  }
])

app.whenReady().then(() => {


  protocol.handle('media', async (request) => {
    const url = new URL(request.url)
    const pathname = decodeURIComponent(url.pathname)
    const filePath = path.resolve(pathname)

    const allowedHost = app.getPath('userData')
    if (!filePath.startsWith(allowedHost)) {
      return new Response(null, { status: 403 })
    }

    if (!fs.existsSync(filePath)) {
      return new Response(null, { status: 404 })
    }

    const stat = fs.statSync(filePath)
    const fileSize = stat.size
    const mimeType = filePath.endsWith('.webm') ? 'video/webm' : 'video/mp4'

    const rangeHeader = request.headers.get('Range')

    if (rangeHeader) {
      const match = rangeHeader.match(/bytes=(\d+)-(\d*)/)
      if (match) {
        const start = parseInt(match[1], 10)
        const end = match[2] ? parseInt(match[2], 10) : fileSize - 1
        const chunkSize = end - start + 1

        const stream = fs.createReadStream(filePath, { start, end })
        const webStream = Readable.toWeb(stream) as ReadableStream

        return new Response(webStream, {
          status: 206,
          headers: {
            'Content-Range': `bytes ${start}-${end}/${fileSize}`,
            'Content-Length': String(chunkSize),
            'Content-Type': mimeType,
            'Accept-Ranges': 'bytes'
          }
        })
      }
    }

    const stream = fs.createReadStream(filePath)
    const webStream = Readable.toWeb(stream) as ReadableStream

    return new Response(webStream, {
      status: 200,
      headers: {
        'Content-Length': String(fileSize),
        'Content-Type': mimeType,
        'Accept-Ranges': 'bytes'
      }
    })
  })

    
  log.info('App ready', {
    version: app.getVersion(),
    platform: process.platform,
    arch: process.arch
  })

  electronApp.setAppUserModelId('com.electron')

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  // Initialize windows and set references
  const mainWindow = createWindow()
  setRecordingMainWindow(mainWindow)
  setMouseTrackingMainWindow(mainWindow)

  // Create the viewer window (hidden, ready to show on demand)
  createViewerWindow()

  // Get available screen sources for recording
  ipcMain.handle('get-sources', async (): Promise<Result<ScreenSource[]>> => {
    try {
      const sources = await desktopCapturer.getSources({ types: ['screen'] })
      const screenSources: ScreenSource[] = sources.map((source) => ({
        id: source.id,
        name: source.name,
        displayId: source.display_id,
        thumbnail: source.thumbnail.toDataURL()
      }))
      return Ok(screenSources)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      log.error('get-sources failed', { error: message })
      return Err(message)
    }
  })

  ipcMain.handle('get-cursor-display', async (): Promise<Result<Electron.Display>> => {
    try {
      const cursorPoint = screen.getCursorScreenPoint()
      const display = screen.getDisplayNearestPoint(cursorPoint)
      return Ok(display)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      log.error('get-cursor-display failed', { error: message })
      return Err(message)
    }
  })

  // Recording IPC handlers
  ipcMain.handle('recording:start', async (): Promise<Result<{ tempPath: string }>> => {
    return startRecording()
  })

  ipcMain.handle('recording:push', async (_event, chunk: ArrayBuffer): Promise<Result<null>> => {
    return pushRecordingChunk(chunk)
  })

  ipcMain.handle(
    'recording:finish',
    async (_event, defaultName: string): Promise<Result<{ zipPath: string }>> => {
      return finishRecording(defaultName)
    }
  )

  // Show open dialog to pick a .ctx file
  ipcMain.handle(
    'recording:show-open-dialog',
    async (): Promise<Result<{ filePath: string }>> => {
      const win = getMainWindow()
      const { canceled, filePaths } = win
        ? await dialog.showOpenDialog(win, {
            title: 'Open Recording',
            filters: [{ name: 'Context Archive', extensions: ['ctx'] }],
            properties: ['openFile']
          })
        : await dialog.showOpenDialog({
            title: 'Open Recording',
            filters: [{ name: 'Context Archive', extensions: ['ctx'] }],
            properties: ['openFile']
          })

      if (canceled || filePaths.length === 0) {
        return Err('Dialog canceled')
      }
      return Ok({ filePath: filePaths[0] })
    }
  )

  // Import a .ctx recording archive and extract it
  ipcMain.handle(
    'recording:import',
    async (
      _event,
      archivePath: string
    ): Promise<Result<{ videoPath: string; eventsPath: string; events: RecordedMouseEvent[] }>> => {
      try {
        const outputDir = await importRecording(archivePath)
        const { videoPath, eventsPath } = await getRecordingItems(outputDir)
        const events = await readEventsFile(eventsPath)
        return Ok({ videoPath, eventsPath, events })
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        log.error('recording:import failed', { error: message })
        return Err(message)
      }
    }
  )

  // Viewer IPC handlers
  ipcMain.handle('viewer:open', async (): Promise<Result<null>> => {
    try {
      let viewer = getViewerWindow()
      if (!viewer) {
        viewer = createViewerWindow()
      }
      viewer.show()
      log.info('Viewer window opened')
      return Ok(null)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      log.error('viewer:open failed', { error: message })
      return Err(message)
    }
  })

  ipcMain.handle('viewer:close', async (): Promise<Result<null>> => {
    try {
      const viewer = getViewerWindow()
      if (viewer) {
        viewer.hide()
        log.info('Viewer window hidden')
      }
      return Ok(null)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      log.error('viewer:close failed', { error: message })
      return Err(message)
    }
  })

  // Send data to the viewer window
  ipcMain.handle(
    'viewer:send-data',
    async (_event, data: unknown): Promise<Result<null>> => {
      try {
        const viewer = getViewerWindow()
        if (viewer) {
          viewer.webContents.send('viewer:data', data)
        }
        return Ok(null)
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        log.error('viewer:send-data failed', { error: message })
        return Err(message)
      }
    }
  )

  app.on('activate', function () {
    if (getMainWindow() === null) {
      const newWindow = createWindow()
      setRecordingMainWindow(newWindow)
      setMouseTrackingMainWindow(newWindow)
    }
  })
})

app.on('window-all-closed', () => {
  log.info('All windows closed')
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  log.info('App quitting')
  stopMouseTracking()
})

process.on('uncaughtException', (error) => {
  log.error('Uncaught exception', error)
})

process.on('unhandledRejection', (reason) => {
  log.error('Unhandled rejection', reason)
})
