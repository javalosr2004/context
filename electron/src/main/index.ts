import { app, shell, BrowserWindow, ipcMain } from 'electron'
import { join } from 'path'
import { spawn, ChildProcess } from 'child_process'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'

let rustProcess: ChildProcess
let requestId = 0
const pendingRequests = new Map<number, (result: unknown) => void>()

function getRustBinaryPath(): string {
  if (app.isPackaged) {
    return join(process.resourcesPath, 'rust-backend')
  } else {
    return join(app.getAppPath(), '..', 'rust-backend', 'target', 'release', 'rust-backend')
  }
}

function startRustBackend(): void {
  rustProcess = spawn(getRustBinaryPath())

  rustProcess.stdout?.on('data', (data) => {
    const lines = data.toString().split('\n').filter((line: string) => line.trim())
    for (const line of lines) {
      try {
        const response = JSON.parse(line)
        const resolver = pendingRequests.get(response.id)
        if (resolver) {
          resolver(response.result)
          pendingRequests.delete(response.id)
        }
      } catch (e) {
        console.error('Failed to parse Rust response:', e)
      }
    }
  })

  rustProcess.stderr?.on('data', (data) => {
    console.error('Rust stderr:', data.toString())
  })

  rustProcess.on('close', (code) => {
    console.log('Rust process exited with code:', code)
  })
}

function sendToRust(method: string, params: unknown = {}): Promise<unknown> {
  return new Promise((resolve) => {
    const id = ++requestId
    pendingRequests.set(id, resolve)
    const request = JSON.stringify({ id, method, params }) + '\n'
    rustProcess.stdin?.write(request)
  })
}

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 900,
    height: 670,
    show: false,
    autoHideMenuBar: true,
    ...(process.platform === 'linux' ? { icon } : {}),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
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
  electronApp.setAppUserModelId('com.electron')

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  startRustBackend()

  ipcMain.handle('rust-invoke', async (_event, method: string, params?: unknown) => {
    return sendToRust(method, params)
  })

  createWindow()

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (rustProcess) {
    rustProcess.kill()
  }
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
