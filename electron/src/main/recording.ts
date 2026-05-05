import { app, BrowserWindow, dialog } from 'electron'
import type { OpenDialogOptions, SaveDialogOptions } from 'electron'
import { basename, join } from 'path'
import { readFile, readdir, rm } from 'fs/promises'
import { FileHandle, mkdir, open, unlink, writeFile } from 'fs/promises'
import { createReadStream, createWriteStream } from 'fs'
import { randomUUID } from 'crypto'
import log from './logger'
import {
  DisplayInfo,
  GetMouseEventsResult,
  LoadedRecordingPayload,
  RecordedMouseEvent
} from '../shared/types'
import archiver from 'archiver'
import { startMouseTracking, stopMouseTracking } from './mouseTracking'
import extract from 'extract-zip'
export interface ActiveRecording {
  handle: FileHandle
  tempPath: string
  startTime: number // ms since UTC epoch
  display: DisplayInfo // captured at recording start; persisted on the recording_start event
  events: RecordedMouseEvent[] // Store events during recording
}

interface StoredRecording {
  archivePath: string
  extractedDir: string
  videoPath: string
  eventsPath: string
  displayName: string
}

let activeRecording: ActiveRecording | null = null
let mainWindowRef: BrowserWindow | null = null
const importedRecordings = new Map<string, StoredRecording>()

function buildArchiveDialogOptions(defaultName: string): SaveDialogOptions {
  return {
    title: 'Save Recording Package',
    defaultPath: join(app.getPath('videos'), defaultName.replace('.webm', '.ctx')),
    filters: [{ name: 'Context Archive', extensions: ['ctx'] }]
  }
}

async function promptForArchivePath(
  window: BrowserWindow | null,
  defaultName: string
): Promise<string | null> {
  const options = buildArchiveDialogOptions(defaultName)
  const result = window
    ? await dialog.showSaveDialog(window, options)
    : await dialog.showSaveDialog(options)

  if (result.canceled || !result.filePath) {
    return null
  }

  return result.filePath
}

async function collectRecordedEvents(
  startTime: number,
  fallbackEvents: RecordedMouseEvent[]
): Promise<RecordedMouseEvent[]> {
  void startTime

  const stopResult = (await stopMouseTracking(
    'stop_and_get_mouse_events'
  )) as GetMouseEventsResult | null
  if (!stopResult?.events) {
    return fallbackEvents
  }

  return stopResult.events.map((captured) => {
    const baseEvent: RecordedMouseEvent = { ...captured.mouse }
    if (captured.axAttributes) {
      baseEvent.axAttributes = captured.axAttributes
    }
    return baseEvent
  })
}

function buildEventsJsonl(
  startTime: number,
  display: DisplayInfo,
  events: RecordedMouseEvent[]
): string {
  const startEvent: RecordedMouseEvent = {
    x: 0,
    y: 0,
    eventType: 'recording_start',
    timeUtcMs: startTime,
    display
  }

  return `${JSON.stringify(startEvent)}\n${events.map((event) => JSON.stringify(event)).join('\n')}`
}

function createArchiveWriter(outputPath: string): {
  archive: ReturnType<typeof archiver>
  archivePromise: Promise<void>
} {
  const output = createWriteStream(outputPath)
  const archive = archiver('zip', { zlib: { level: 5 } })
  const archivePromise = new Promise<void>((resolve, reject) => {
    output.on('close', resolve)
    archive.on('error', reject)
  })

  archive.pipe(output)
  return { archive, archivePromise }
}

function appendRecordingArchiveContents(
  archive: ReturnType<typeof archiver>,
  tempPath: string,
  jsonl: string
): void {
  archive.append(createReadStream(tempPath), { name: 'recording.webm' })
  archive.append(jsonl, { name: 'events.jsonl' })
}

async function cleanupTempRecording(tempPath: string): Promise<void> {
  await unlink(tempPath).catch(() => {})
}

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

export async function startRecording(
  display: DisplayInfo
): Promise<{ ok: true; payload: null } | { ok: false; error: string }> {
  if (activeRecording) {
    return { ok: false, error: 'Recording already in progress' }
  }

  try {
    // Start mouse tracking and wait for all apps to be preloaded
    await startMouseTracking()

    // Start temporary chunk storage.
    const startTime = Date.now()
    const tempPath = join(app.getPath('temp'), `screen-recording-${startTime}.webm`)
    const handle = await open(tempPath, 'w')
    activeRecording = { handle, tempPath, startTime, display, events: [] }

    log.info('recording:start', { tempPath, startTime, display })
    return { ok: true, payload: null }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    log.error('recording:start failed', { error: message })
    return { ok: false, error: message }
  }
}

export async function pushRecordingChunk(
  chunk: ArrayBuffer
): Promise<{ ok: true; payload: null } | { ok: false; error: string }> {
  if (!activeRecording) {
    return { ok: false, error: "Recording hasn't started." }
  }

  try {
    const buffer = Buffer.from(chunk)
    log.info('recording:push', { bufferLength: buffer.length })
    await activeRecording.handle.write(buffer)
    return { ok: true, payload: null }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    log.error('recording:push failed', { error: message })
    return { ok: false, error: message }
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
 * @returns Result containing the opaque id and renderer-safe media URL
 */
export async function finishRecording(
  defaultName: string
): Promise<{ ok: true; payload: LoadedRecordingPayload } | { ok: false; error: string }> {
  if (!activeRecording) {
    return { ok: false, error: 'No active recording' }
  }

  // Close the file handle
  try {
    await activeRecording.handle.close()
  } catch (error) {
    log.error('recording:finish close handle failed', { error })
  }

  const { tempPath, startTime, display, events: fallbackEvents } = activeRecording
  let events = fallbackEvents
  activeRecording = null

  try {
    const win = mainWindowRef ?? BrowserWindow.getFocusedWindow()
    const archivePath = await promptForArchivePath(win, defaultName)
    if (!archivePath) {
      await cleanupTempRecording(tempPath)
      log.info('recording:finish canceled, temp deleted')
      return { ok: false, error: 'Save canceled' }
    }

    events = await collectRecordedEvents(startTime, events)
    const jsonl = buildEventsJsonl(startTime, display, events)
    const { archive, archivePromise } = createArchiveWriter(archivePath)
    appendRecordingArchiveContents(archive, tempPath, jsonl)
    await archive.finalize()
    await archivePromise
    await cleanupTempRecording(tempPath)

    const payload = await loadRecordingArchive(archivePath)
    log.info('recording:finish created', {
      archivePath,
      recordingId: payload.recordingId,
      eventCount: events.length
    })
    return { ok: true, payload }
  } catch (error) {
    await cleanupTempRecording(tempPath)
    const message = error instanceof Error ? error.message : String(error)
    log.error('recording:finish failed', { error: message })
    return { ok: false, error: message }
  }
}

const VALID_VIDEO_EXTENSIONS = ['.webm', '.mp4']
const VALID_EVENTS_EXTENSION = '.jsonl'

export async function getRecordingItems(
  outputDir: string
): Promise<{ videoPath: string; eventsPath: string }> {
  const entries = await readdir(outputDir)

  const videoFile = entries.find((f) => VALID_VIDEO_EXTENSIONS.some((ext) => f.endsWith(ext)))
  const eventsFile = entries.find((f) => f.endsWith(VALID_EVENTS_EXTENSION))

  if (!videoFile || !eventsFile) {
    throw new Error(
      `Recording items missing in ${outputDir}: expected 1 video (${VALID_VIDEO_EXTENSIONS.join('|')}) and 1 ${VALID_EVENTS_EXTENSION}`
    )
  }

  if (entries.length !== 2) {
    throw new Error(`Invalid recording archive: expected exactly 2 items, found ${entries.length}`)
  }

  return {
    videoPath: join(outputDir, videoFile),
    eventsPath: join(outputDir, eventsFile)
  }
}

const IMPORT_CACHE_DIR = 'recording-imports'

function clearRecordingRegistry(): void {
  importedRecordings.clear()
}

async function cleanupOldImports(cacheBase: string): Promise<void> {
  try {
    const entries = await readdir(cacheBase)
    await Promise.all(
      entries.map((entry) => rm(join(cacheBase, entry), { recursive: true, force: true }))
    )
  } catch {
    // Directory may not exist yet, that's fine
  }
  clearRecordingRegistry()
}

async function extractRecordingArchive(inputFile: string): Promise<string> {
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

function buildVideoUrl(recordingId: string): string {
  return `media://recording/${recordingId}`
}

export function getRecordingVideoPath(recordingId: string): string | null {
  return importedRecordings.get(recordingId)?.videoPath ?? null
}

export async function loadRecordingArchive(archivePath: string): Promise<LoadedRecordingPayload> {
  const extractedDir = await extractRecordingArchive(archivePath)
  const { videoPath, eventsPath } = await getRecordingItems(extractedDir)
  const events = await readEventsFile(eventsPath)
  const recordingId = randomUUID()
  const displayName = basename(archivePath)

  importedRecordings.set(recordingId, {
    archivePath,
    extractedDir,
    videoPath,
    eventsPath,
    displayName
  })

  return {
    recordingId,
    displayName,
    videoUrl: buildVideoUrl(recordingId),
    events
  }
}

export async function pickRecording(): Promise<
  { ok: true; payload: LoadedRecordingPayload } | { ok: false; error: string }
> {
  const win = mainWindowRef ?? BrowserWindow.getFocusedWindow()
  const options: OpenDialogOptions = {
    title: 'Open Recording',
    filters: [{ name: 'Context Archive', extensions: ['ctx'] }],
    properties: ['openFile']
  }

  const result = win
    ? await dialog.showOpenDialog(win, options)
    : await dialog.showOpenDialog(options)

  if (result.canceled || result.filePaths.length === 0) {
    return { ok: false, error: 'Dialog canceled' }
  }

  try {
    return { ok: true, payload: await loadRecordingArchive(result.filePaths[0]) }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    log.error('recording:pick failed', { error: message })
    return { ok: false, error: message }
  }
}

export async function saveRecordingEvents(
  recordingId: string,
  events: RecordedMouseEvent[]
): Promise<void> {
  const storedRecording = importedRecordings.get(recordingId)
  if (!storedRecording) {
    throw new Error('Recording not found or expired')
  }

  await saveEventsFile(storedRecording.eventsPath, storedRecording.archivePath, events)
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
