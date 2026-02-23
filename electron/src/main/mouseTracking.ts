import { screen, BrowserWindow, app } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import { uIOhook, UiohookMouseEvent } from 'uiohook-napi'
import log from './logger'
import type { MouseClick } from '../shared/types'
import { sendRpcRequest, handleRpcResponse, cleanupPendingRequests } from './rpc'

let mainWindow: BrowserWindow | null = null
let mouseTrackingInterval: NodeJS.Timeout | null = null
let mouseTrackingActive = false
let rustProcess: ChildProcess | null = null
let stdoutBuffer = ''

function getRustBinaryPath(): string {
  if (app.isPackaged) {
    // Production: binary is in resources/bin
    return path.join(process.resourcesPath, 'bin', 'capture')
  } else {
    // Development: build:rust copies binary to resources/bin
    return path.join(__dirname, '../../resources/bin/capture')
  }
}

export function setMainWindow(window: BrowserWindow | null): void {
  mainWindow = window
}

export function getRustProcess(): ChildProcess | null {
  return rustProcess
}

function getMouseButton(button: number): MouseClick['button'] {
  switch (button) {
    case 1:
      return 'left'
    case 2:
      return 'right'
    default:
      return 'middle'
  }
}

function handleMouseClick(e: UiohookMouseEvent): void {
  log.info('mouseTracking:click', { x: e.x, y: e.y, button: e.button })
  // if (rustProcess) {
  //   sendRpcRequest(rustProcess, 'get_mouse_events')
  //     .then((result) => log.info('rust-backend:mouse_events', result))
  //     .catch((err) => log.error('rust-backend:mouse_events failed', { error: err.message }))
  // }
  if (mainWindow && !mainWindow.isDestroyed()) {
    const click: MouseClick = {
      x: e.x,
      y: e.y,
      button: getMouseButton(e.button as number),
      timestamp: Date.now()
    }

    // Send to renderer for UI updates
    mainWindow.webContents.send('mouse-click', click)
  }
}

export function startMouseTracking(): void {
  if (mouseTrackingActive) return

  // Spawn the Rust backend process
  const binaryPath = getRustBinaryPath()
  log.info('mouseTracking:spawning rust backend', { path: binaryPath, isPackaged: app.isPackaged })

  rustProcess = spawn(binaryPath)

  rustProcess.stdout?.on('data', (data) => {
    // Buffer data and process complete lines
    stdoutBuffer += data.toString()
    const lines = stdoutBuffer.split('\n')
    stdoutBuffer = lines.pop() || '' // Keep incomplete line in buffer

    for (const line of lines) {
      if (line.trim()) {
        handleRpcResponse(line)
      }
    }
  })

  rustProcess.stderr?.on('data', (data) => {
    log.error('rust-backend:stderr', { data: data.toString() })
  })

  rustProcess.on('error', (err) => {
    log.error('rust-backend:error', { error: err.message })
  })

  rustProcess.on('close', (code) => {
    log.info('rust-backend:closed', { code })
    rustProcess = null
    cleanupPendingRequests()
    stdoutBuffer = ''
  })

  sendRpcRequest(rustProcess, 'start_mouse_listener')
    .then(() => log.info('rust-backend:mouse_listener started'))
    .catch((err) => log.error('rust-backend:start_mouse_listener failed', { error: err.message }))

  // Start position tracking at ~60fps
  mouseTrackingInterval = setInterval(() => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      const point = screen.getCursorScreenPoint()
      mainWindow.webContents.send('mouse-position', { x: point.x, y: point.y })
    }
  }, 1000 / 60)

  // Start click tracking via uiohook
  uIOhook.on('click', handleMouseClick)
  uIOhook.start()

  mouseTrackingActive = true
  log.info('mouseTracking:started')
}

export function stopMouseTracking(): void {
  if (!mouseTrackingActive) return

  if (rustProcess) {
    sendRpcRequest(rustProcess, 'stop_mouse_listener')
      .then(() => log.info('rust-backend:mouse_listener started'))
      .catch((err) => log.error('rust-backend:start_mouse_listener failed', { error: err.message }))
  }

  // Stop position tracking
  if (mouseTrackingInterval) {
    clearInterval(mouseTrackingInterval)
    mouseTrackingInterval = null
  }

  // Stop click tracking
  uIOhook.off('click', handleMouseClick)
  uIOhook.stop()

  // Kill the Rust backend process

  mouseTrackingActive = false
  log.info('mouseTracking:stopped')
}
