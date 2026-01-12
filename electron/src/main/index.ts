import { app, shell, BrowserWindow, ipcMain } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'
import { captureService } from './capture'
import log from './logger'

let mainWindow: BrowserWindow | null = null

function createWindow(): void {
  log.info('Creating main window')

  mainWindow = new BrowserWindow({
    width: 900,
    height: 670,
    show: true,
    autoHideMenuBar: true,
    ...(process.platform === 'linux' ? { icon } : {}),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  })

  captureService.setMainWindow(mainWindow)

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

  // Capture service IPC handlers
  ipcMain.handle('capture:start', async (_event, fps?: number) => {
    try {
      await captureService.start(fps)
      return { success: true, status: captureService.getStatus() }
    } catch (error) {
      log.error('Failed to start capture', error)
      return { success: false, error: String(error) }
    }
  })

  ipcMain.handle('capture:stop', () => {
    captureService.stop()
    return { success: true, status: captureService.getStatus() }
  })

  ipcMain.handle('capture:status', () => {
    return captureService.getStatus()
  })

  ipcMain.handle('capture:go-status', async () => {
    return await captureService.getGoStatus()
  })

  createWindow()

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  log.info('All windows closed')
  captureService.stop()

  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  log.info('App quitting')
  captureService.stop()
})

process.on('uncaughtException', (error) => {
  log.error('Uncaught exception', error)
})

process.on('unhandledRejection', (reason) => {
  log.error('Unhandled rejection', reason)
})
