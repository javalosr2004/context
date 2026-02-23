import { BrowserWindow, shell, screen } from 'electron'
import { join } from 'path'
import { is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'
import log from './logger'

let mainWindow: BrowserWindow | null = null
let viewerWindow: BrowserWindow | null = null

export function createWindow(): BrowserWindow {
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

  return mainWindow
}

export function createViewerWindow(): BrowserWindow {
  log.info('Creating viewer window')

  const primaryDisplay = screen.getPrimaryDisplay()
  const { width, height } = primaryDisplay.workAreaSize

  viewerWindow = new BrowserWindow({
    width,
    height,
    x: 0,
    y: 0,
    show: false,
    transparent: true,
    frame: false,
    hasShadow: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    focusable: false,
    webPreferences: {
      preload: join(__dirname, '../preload/index.mjs'),
      sandbox: false
    }
  })

  viewerWindow.setIgnoreMouseEvents(true)

  viewerWindow.on('closed', () => {
    viewerWindow = null
  })

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    viewerWindow.loadURL(`${process.env['ELECTRON_RENDERER_URL']}/viewer.html`)
  } else {
    viewerWindow.loadFile(join(__dirname, '../renderer/viewer.html'))
  }

  return viewerWindow
}

export function getMainWindow(): BrowserWindow | null {
  return mainWindow
}

export function getViewerWindow(): BrowserWindow | null {
  return viewerWindow
}
