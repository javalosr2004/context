import { screen, BrowserWindow, app } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import log from './logger'
import { sendRpcRequest, handleRpcResponse, cleanupPendingRequests } from './rpc'

let mainWindow: BrowserWindow | null = null
let mouseTrackingInterval: NodeJS.Timeout | null = null
let mouseTrackingActive = false
let rustProcess: ChildProcess | null = null
let stdoutBuffer = ''

function getRustBinaryPath(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'bin', 'capture')
  } else {
    return path.join(__dirname, '../../resources/bin/capture')
  }
}

export function setMainWindow(window: BrowserWindow | null): void {
  mainWindow = window
}

export function getRustProcess(): ChildProcess | null {
  return rustProcess
}

export async function startMouseTracking(): Promise<void> {
  if (mouseTrackingActive) return

  const binaryPath = getRustBinaryPath()
  log.info('mouseTracking:spawning rust backend', { path: binaryPath, isPackaged: app.isPackaged })

  rustProcess = spawn(binaryPath)

  rustProcess.stdout?.on('data', (data) => {
    stdoutBuffer += data.toString()
    const lines = stdoutBuffer.split('\n')
    stdoutBuffer = lines.pop() || ''

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

  await sendRpcRequest(rustProcess, 'activate_apps')
  log.info('rust-backend:apps preloaded')

  await sendRpcRequest(rustProcess, 'start_mouse_listener')
  log.info('rust-backend:mouse_listener started')

  mouseTrackingInterval = setInterval(() => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      const point = screen.getCursorScreenPoint()
      mainWindow.webContents.send('mouse-position', { x: point.x, y: point.y })
    }
  }, 1000 / 60)

  mouseTrackingActive = true
  log.info('mouseTracking:started')
}

export async function stopMouseTracking(
  method: 'stop_mouse_listener' | 'stop_and_get_mouse_events' = 'stop_mouse_listener'
): Promise<unknown | null> {
  if (!mouseTrackingActive) return

  let result: unknown | null = null

  if (rustProcess) {
    try {
      result = await sendRpcRequest(rustProcess, method)
      log.info('rust-backend:mouse_listener stopped', { method })
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      log.error('rust-backend:stop_mouse_listener failed', { error: message, method })
    }
  }

  if (mouseTrackingInterval) {
    clearInterval(mouseTrackingInterval)
    mouseTrackingInterval = null
  }

  mouseTrackingActive = false
  log.info('mouseTracking:stopped')
  return result
}
