import log from 'electron-log/main'
import { app } from 'electron'
import { join } from 'path'

// Configure file transport
log.transports.file.level = 'info'
log.transports.file.maxSize = 10 * 1024 * 1024 // 10MB
log.transports.file.format = '{y}-{m}-{d} {h}:{i}:{s}.{ms} [{level}] {text}'
log.transports.file.resolvePathFn = (): string =>
  join(app.getPath('userData'), 'logs', 'main.log')

// Configure console transport for dev
log.transports.console.level = app.isPackaged ? 'warn' : 'debug'
log.transports.console.format = '[{level}] {text}'

// Initialize for renderer process logging
log.initialize()

export const logger = log
export default log
