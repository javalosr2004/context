import { app, shell, BrowserWindow, ipcMain, desktopCapturer, screen } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'
import log from './logger'
import { FileHandle, open } from 'fs/promises'
import type { ScreenSource } from '../shared/types'
import { Result, Ok, Err } from '../shared/types'

interface ActiveRecording {
  handle: FileHandle
  tempPath: string
}

let mainWindow: BrowserWindow | null = null
let mouseTrackingInterval: NodeJS.Timeout | null = null
let activeRecording: ActiveRecording | null = null

function startMouseTracking(): void {
  if (mouseTrackingInterval) return

  mouseTrackingInterval = setInterval(() => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      const point = screen.getCursorScreenPoint()
      mainWindow.webContents.send('mouse-position', { x: point.x, y: point.y })
    }
  }, 1000 / 60) // ~60fps
}

function stopMouseTracking(): void {
  if (mouseTrackingInterval) {
    clearInterval(mouseTrackingInterval)
    mouseTrackingInterval = null
  }
}

async function startRecording(): Promise<Result<{ tempPath: string }>> {
  if (activeRecording) {
    return Err('Recording already in progress')
  }

  try {
    // Start temporary chunk storage.
    const tempPath = join(app.getPath('temp'), `screen-recording-${Date.now()}.webm`)
    const handle = await open(tempPath, 'w')
    activeRecording = { handle, tempPath }

    log.info('recording:start', { tempPath })
    return Ok({ tempPath })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    log.error('recording:start failed', { error: message })
    return Err(message)
  }
}

function createWindow(): void {
  log.info('Creating main window')

  mainWindow = new BrowserWindow({
    width: 900,
    height: 670,
    show: true,
    autoHideMenuBar: true,
    ...(process.platform === 'linux' ? { icon } : {}),
    webPreferences: {
      preload: join(__dirname, '../preload/index.mjs'),
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    log.debug('Main window ready to show')
    mainWindow!.show()
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(() => {
  log.info('App ready', {
    version: app.getVersion(),
    platform: process.platform,
    arch: process.arch
  })

  electronApp.setAppUserModelId('com.electron')

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

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

  // Mouse tracking controls
  ipcMain.on('start-mouse-tracking', () => {
    startMouseTracking()
  })

  ipcMain.on('stop-mouse-tracking', () => {
    stopMouseTracking()
  })

  ipcMain.on('recording:start', () => {})

  createWindow()

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
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
