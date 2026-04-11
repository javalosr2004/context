import { app, BrowserWindow, dialog } from 'electron'
import { join } from 'path'
import { readFile, readdir, rm } from 'fs/promises'
import { FileHandle, mkdir, open, unlink, writeFile } from 'fs/promises'
import { createReadStream, createWriteStream } from 'fs'
import log from './logger'
import {
  Result,
  Ok,
  Err,
  GetMouseEventsResult,
  RustCapturedMouseEvent,
  RecordedMouseEvent
} from '../shared/types'
import archiver from 'archiver'
import { sendRpcRequest } from './rpc'
import { getRustProcess, startMouseTracking, stopMouseTracking } from './mouseTracking'
import extract from 'extract-zip'
export interface ActiveRecording {
  handle: FileHandle
  tempPath: string
  startTime: number // ms since UTC epoch
  events: RecordedMouseEvent[] // Store events during recording
}

let activeRecording: ActiveRecording | null = null
let mainWindowRef: BrowserWindow | null = null

export function setMainWindow(window: BrowserWindow | null): void {
  mainWindowRef = window
}

export function getActiveRecording(): ActiveRecording | null {
  return activeRecording
}

export function setEvents(events: RecordedMouseEvent[]): void {
  if (activeRecording) {
    activeRecording.events = events
  }
}

export function addEventToRecording(event: RecordedMouseEvent): void {
  if (activeRecording) {
    activeRecording.events.push(event)
  }
}

export async function startRecording(): Promise<Result<{ tempPath: string }>> {
  if (activeRecording) {
    return Err('Recording already in progress')
  }

  try {
    // Start mouse tracking and wait for all apps to be preloaded
    await startMouseTracking()

    // Start temporary chunk storage.
    const startTime = Date.now()
    const tempPath = join(app.getPath('temp'), `screen-recording-${startTime}.webm`)
    const handle = await open(tempPath, 'w')


    activeRecording = { handle, tempPath, startTime, events: [] } 

    log.info('recording:start', { tempPath, startTime })
    return Ok({ tempPath })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    log.error('recording:start failed', { error: message })
    return Err(message)
  }
}

export async function pushRecordingChunk(chunk: ArrayBuffer): Promise<Result<null>> {
  if (!activeRecording) {
    return Err("Recording hasn't started.")
  }

  try {
    const buffer = Buffer.from(chunk)
    log.info('recording:push', { bufferLength: buffer.length })
    await activeRecording.handle.write(buffer)
    return Ok(null)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    log.error('recording:push failed', { error: message })
    return Err(message)
  }
}

/**
 * Finishes the recording and creates a zip file containing the video and events.
 * This function:
 * 1. Closes the file handle
 * 2. Streams the video from tempPath directly into a zip (memory efficient)
 * 3. Adds mouse click events as JSONL
 * 4. Shows save dialog for the zip
 * 5. Cleans up the temp video file
 *
 * @param defaultName Default name for the file (e.g., "recording-123.webm")
 * @returns Result containing the path to the created zip file
 */
export async function finishRecording(defaultName: string): Promise<Result<{ zipPath: string }>> {
  if (!activeRecording) {
    return Err('No active recording')
  }

  // Stop mouse tracking
  stopMouseTracking()

  // Close the file handle
  try {
    await activeRecording.handle.close()
  } catch (error) {
    log.error('recording:finish close handle failed', { error })
  }

  let { tempPath, startTime, events } = activeRecording
  activeRecording = null

  try {
    const win = mainWindowRef ?? BrowserWindow.getFocusedWindow()

    // Show save dialog for zip file
    const zipName = defaultName.replace('.webm', '.ctx')
    const dialogOptions = {
      title: 'Save Recording Package',
      defaultPath: join(app.getPath('videos'), zipName),
      filters: [{ name: 'Context Archive', extensions: ['ctx'] }]
    }
    const { canceled, filePath } = win
      ? await dialog.showSaveDialog(win, dialogOptions)
      : await dialog.showSaveDialog(dialogOptions)

    if (canceled || !filePath) {
      // Clean up temp file
      await unlink(tempPath).catch(() => {})
      log.info('recording:finish canceled, temp deleted')
      return Err('Save canceled')
    }

    // Create zip using archiver with streaming
    const output = createWriteStream(filePath)
    const archive = archiver('zip', { zlib: { level: 5 } })

    // Create a promise that resolves when the archive is finalized
    const archivePromise = new Promise<void>((resolve, reject) => {
      output.on('close', resolve)
      archive.on('error', reject)
    })

    // Pipe archive data to the output file
    archive.pipe(output)

    // Stream the video file from tempPath (no memory loading)
    archive.append(createReadStream(tempPath), { name: 'recording.webm' })

    // Add events as JSONL
    // Send RPC request to Rust backend to save events
    const rustProcess = getRustProcess()
    if (rustProcess) {
      await sendRpcRequest(rustProcess, 'get_mouse_events')
        .then((result) => {
          const eventResult = result as GetMouseEventsResult
          if (eventResult.events) {
            events = eventResult.events.map((captured: RustCapturedMouseEvent) => {
              const baseEvent: RecordedMouseEvent = { ...captured.mouse }
              if (captured.axAttributes) {
                baseEvent.axAttributes = captured.axAttributes
              }
              return baseEvent
            })
          }
        })
        .catch((err) => log.error('rust-backend:mouse_events failed', { error: err.message }))
    } 
    // Emit synthetic recording_start event as timestamp baseline
    const startEvent: RecordedMouseEvent = {
      x: 0,
      y: 0,
      eventType: 'recording_start',
      timeUtcMs: (startTime)
    }
    let jsonlContent = JSON.stringify(startEvent) + "\n"
    jsonlContent += events.map((event) => JSON.stringify(event)).join('\n') ?? ''
    archive.append(jsonlContent, { name: 'events.jsonl' })

    // Finalize the archive
    await archive.finalize()
    await archivePromise

    // Clean up temp video file
    await unlink(tempPath).catch(() => {})

    log.info('recording:finish created', { zipPath: filePath, eventCount: events.length })
    return Ok({ zipPath: filePath })
  } catch (error) {
    // Clean up temp file on error
    await unlink(tempPath).catch(() => {})
    const message = error instanceof Error ? error.message : String(error)
    log.error('recording:finish failed', { error: message })
    return Err(message)
  }
}

const VALID_VIDEO_EXTENSIONS = ['.webm', '.mp4']
const VALID_EVENTS_EXTENSION = '.jsonl'

export async function getRecordingItems(
  outputDir: string
): Promise<{ videoPath: string; eventsPath: string }> {
  const entries = await readdir(outputDir)

  const videoFile = entries.find((f) =>
    VALID_VIDEO_EXTENSIONS.some((ext) => f.endsWith(ext))
  )
  const eventsFile = entries.find((f) => f.endsWith(VALID_EVENTS_EXTENSION))

  if (!videoFile || !eventsFile) {
    throw new Error(
      `Recording items missing in ${outputDir}: expected 1 video (${VALID_VIDEO_EXTENSIONS.join('|')}) and 1 ${VALID_EVENTS_EXTENSION}`
    )
  }

  if (entries.length !== 2) {
    throw new Error(
      `Invalid recording archive: expected exactly 2 items, found ${entries.length}`
    )
  }

  return {
    videoPath: join(outputDir, videoFile),
    eventsPath: join(outputDir, eventsFile)
  }
}

const IMPORT_CACHE_DIR = 'recording-imports'

async function cleanupOldImports(cacheBase: string): Promise<void> {
  try {
    const entries = await readdir(cacheBase)
    await Promise.all(
      entries.map((entry) => rm(join(cacheBase, entry), { recursive: true, force: true }))
    )
  } catch {
    // Directory may not exist yet, that's fine
  }
}

export async function importRecording(inputFile: string): Promise<string> {
  const cacheBase = join(app.getPath('userData'), 'cache', IMPORT_CACHE_DIR)
  const timestamp = Date.now()
  const outputPath = join(cacheBase, String(timestamp))

  try {
    // Clean up previous imports before extracting new one
    await cleanupOldImports(cacheBase)

    await mkdir(outputPath, { recursive: true })
    await extract(inputFile, { dir: outputPath })
    log.info('recording:import', { inputFile, outputPath })
    return outputPath
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    log.error('recording:import failed', { error: message, inputFile })
    throw error
  }
}

export async function readEventsFile(eventsPath: string): Promise<RecordedMouseEvent[]> {
  const content = await readFile(eventsPath, 'utf-8')
  const lines = content.trim().split('\n').filter(Boolean)
  return lines.map((line) => JSON.parse(line) as RecordedMouseEvent)
}

export async function saveEventsFile(
  eventsPath: string,
  archivePath: string,
  events: RecordedMouseEvent[]
): Promise<void> {
  // Write to extracted cache
  const jsonl = events.map((e) => JSON.stringify(e)).join('\n')
  await writeFile(eventsPath, jsonl, 'utf-8')

  // Re-pack the .ctx archive from the extracted directory
  const extractedDir = join(eventsPath, '..')
  const { videoPath } = await getRecordingItems(extractedDir)

  const output = createWriteStream(archivePath)
  const archive = archiver('zip', { zlib: { level: 5 } })
  const archivePromise = new Promise<void>((resolve, reject) => {
    output.on('close', resolve)
    archive.on('error', reject)
  })
  archive.pipe(output)
  archive.append(createReadStream(videoPath), { name: 'recording.webm' })
  archive.append(jsonl, { name: 'events.jsonl' })
  await archive.finalize()
  await archivePromise

  log.info('recording:save-events', { eventsPath, archivePath, eventCount: events.length })
}
