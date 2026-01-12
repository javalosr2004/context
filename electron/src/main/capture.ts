import { app, BrowserWindow } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import { join } from 'path'
import log from './logger'

export interface GoStatus {
  running: boolean
  fps: number
  captureCount: number
  uptime: number
  outputDir: string
}

interface CaptureConfig {
  fps: number
  port: number
}

export class CaptureService {
  private isRunning = false
  private goProcess: ChildProcess | null = null
  private mainWindow: BrowserWindow | null = null
  private healthCheckInterval: NodeJS.Timeout | null = null
  private config: CaptureConfig = { fps: 10, port: 8765 }
  private restartAttempts = 0
  private readonly maxRestartAttempts = 3

  private getGolangDir(): string {
    if (app.isPackaged) {
      return join(process.resourcesPath, 'golang-backend')
    }
    return join(app.getAppPath(), '..', 'golang-backend')
  }

  private get goServerUrl(): string {
    return `http://localhost:${this.config.port}`
  }

  setMainWindow(window: BrowserWindow): void {
    this.mainWindow = window
  }

  private sendStatus(): void {
    if (this.mainWindow && !this.mainWindow.isDestroyed()) {
      this.mainWindow.webContents.send('capture:status', {
        isRunning: this.isRunning,
        capturesDir: join(this.getGolangDir(), 'images')
      })
    }
  }

  private async checkHealth(): Promise<boolean> {
    try {
      const response = await fetch(`${this.goServerUrl}/health`, {
        signal: AbortSignal.timeout(2000)
      })
      return response.ok
    } catch {
      return false
    }
  }

  private async waitForReady(maxWait = 5000): Promise<boolean> {
    const start = Date.now()
    while (Date.now() - start < maxWait) {
      if (await this.checkHealth()) {
        log.info('Go backend is ready')
        return true
      }
      await new Promise((r) => setTimeout(r, 200))
    }
    return false
  }

  private startHealthMonitoring(): void {
    this.healthCheckInterval = setInterval(async () => {
      if (!this.isRunning) return

      const healthy = await this.checkHealth()
      if (!healthy) {
        log.warn('Go backend health check failed')
        await this.handleUnhealthyBackend()
      }
    }, 5000)
  }

  private async handleUnhealthyBackend(): Promise<void> {
    if (this.restartAttempts >= this.maxRestartAttempts) {
      log.error('Max restart attempts reached, stopping capture service')
      this.stop()
      return
    }

    log.info(`Attempting to restart Go backend (attempt ${this.restartAttempts + 1})`)
    this.restartAttempts++

    this.killGoProcess()
    await new Promise((r) => setTimeout(r, 1000))
    await this.spawnGoProcess()
  }

  private killGoProcess(): void {
    if (this.goProcess) {
      this.goProcess.kill('SIGTERM')
      this.goProcess = null
    }
  }

  private async spawnGoProcess(): Promise<void> {
    const golangDir = this.getGolangDir()
    const binaryPath = join(golangDir, 'capture')

    log.info('Spawning Go capture daemon', {
      binaryPath,
      fps: this.config.fps,
      port: this.config.port
    })

    this.goProcess = spawn(
      binaryPath,
      ['-fps', this.config.fps.toString(), '-port', this.config.port.toString()],
      {
        cwd: golangDir,
        stdio: ['ignore', 'pipe', 'pipe']
      }
    )

    this.goProcess.stdout?.on('data', (data) => {
      log.debug('[Go stdout]', data.toString().trim())
    })

    this.goProcess.stderr?.on('data', (data) => {
      log.info('[Go stderr]', data.toString().trim())
    })

    this.goProcess.on('close', (code) => {
      log.info('Go process exited', { code })
      if (this.isRunning && code !== 0) {
        this.handleUnhealthyBackend()
      }
    })

    this.goProcess.on('error', (err) => {
      log.error('Failed to start Go process', err)
      this.isRunning = false
      this.goProcess = null
      this.sendStatus()
    })
  }

  async start(fps: number = 10): Promise<void> {
    if (this.isRunning) {
      log.info('Capture service already running')
      return
    }

    this.config.fps = fps
    log.info('Starting capture service', { fps })

    await this.spawnGoProcess()

    const ready = await this.waitForReady()
    if (!ready) {
      log.error('Go backend failed to become ready')
      this.killGoProcess()
      throw new Error('Backend failed to start')
    }

    this.isRunning = true
    this.restartAttempts = 0
    this.startHealthMonitoring()

    log.info('Capture service started successfully')
    this.sendStatus()
  }

  stop(): void {
    if (!this.isRunning) {
      log.info('Capture service not running')
      return
    }

    log.info('Stopping capture service')

    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval)
      this.healthCheckInterval = null
    }

    this.killGoProcess()
    this.isRunning = false

    log.info('Capture service stopped')
    this.sendStatus()
  }

  async getGoStatus(): Promise<GoStatus | null> {
    if (!this.isRunning) return null

    try {
      const response = await fetch(`${this.goServerUrl}/status`)
      return (await response.json()) as GoStatus
    } catch {
      return null
    }
  }

  getStatus(): { isRunning: boolean; capturesDir: string } {
    return {
      isRunning: this.isRunning,
      capturesDir: join(this.getGolangDir(), 'images')
    }
  }
}

export const captureService = new CaptureService()
