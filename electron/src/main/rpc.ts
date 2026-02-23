import type { ChildProcess } from 'child_process'
import log from './logger'

// JSON-RPC request/response handling
let requestId = 0
type RpcCallback = (error: Error | null, result?: unknown) => void
const pendingRequests = new Map<number, RpcCallback>()

export function sendRpcRequest(
  process: ChildProcess | null,
  method: string,
  params: object = {}
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    if (!process) {
      reject(new Error('Rust process not running'))
      return
    }

    const id = ++requestId
    pendingRequests.set(id, (error, result) => {
      if (error) reject(error)
      else resolve(result)
    })

    const request = JSON.stringify({ id, method, params }) + '\n'
    process.stdin?.write(request)
  })
}

export function handleRpcResponse(line: string): void {
  try {
    const response = JSON.parse(line)
    const callback = pendingRequests.get(response.id)

    if (callback) {
      pendingRequests.delete(response.id)
      if (response.error) {
        callback(new Error(response.error.message || 'RPC error'))
      } else {
        callback(null, response.result)
      }
    } else {
      // No matching request - might be a notification/event from Rust
      log.info('rust-backend:event', response)
    }
  } catch (err) {
    log.error('rust-backend:parse-error', { line, error: String(err) })
  }
}

export function cleanupPendingRequests(): void {
  for (const [id, callback] of pendingRequests) {
    callback(new Error('Process closed'))
    pendingRequests.delete(id)
  }
}
