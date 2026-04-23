import { useCallback, useEffect, useRef, useState } from 'react'
import type { LoadedRecordingPayload } from '../../../../shared/types'
import { buildAnnotatorEvents } from './model'
import type { AnnotatorRecordingLoad } from './types'

async function captureScreen(sourceId: string): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
      mandatory: {
        chromeMediaSource: 'desktop',
        chromeMediaSourceId: sourceId,
        minWidth: 1280,
        minHeight: 720,
        maxWidth: 1920,
        maxHeight: 1080
      }
    } as MediaTrackConstraints
  })
}

interface UseAnnotatorRecordingOptions {
  onLoad: (recording: AnnotatorRecordingLoad) => void
  onError: (error: string | null) => void
  onLoadingChange: (isLoading: boolean) => void
}

interface UseAnnotatorRecordingResult {
  isRecording: boolean
  isRecordingLoading: boolean
  startOrStopRecording: () => Promise<void>
  importRecording: () => Promise<void>
  resetRecordingResources: () => void
}

export function useAnnotatorRecording({
  onLoad,
  onError,
  onLoadingChange
}: UseAnnotatorRecordingOptions): UseAnnotatorRecordingResult {
  const [isRecording, setIsRecording] = useState(false)
  const [isRecordingLoading, setIsRecordingLoading] = useState(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const writePromisesRef = useRef<Promise<void>[]>([])

  const resetRecordingResources = useCallback((): void => {
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop()
    }

    streamRef.current?.getTracks().forEach((track) => track.stop())
    recorderRef.current = null
    streamRef.current = null
    writePromisesRef.current = []
  }, [])

  const loadRecordingIntoEditor = useCallback(
    (payload: LoadedRecordingPayload): void => {
      onLoad({
        recordingId: payload.recordingId,
        displayName: payload.displayName,
        videoUrl: payload.videoUrl,
        events: buildAnnotatorEvents(payload.events),
        rawEvents: payload.events
      })
    },
    [onLoad]
  )

  useEffect(() => resetRecordingResources, [resetRecordingResources])

  const importRecording = useCallback(async (): Promise<void> => {
    onLoadingChange(true)
    onError(null)

    try {
      const result = await window.api.pickRecording()
      if (result.ok) {
        loadRecordingIntoEditor(result.payload)
      } else if (result.error !== 'Dialog canceled') {
        onError(result.error)
      }
    } finally {
      onLoadingChange(false)
    }
  }, [loadRecordingIntoEditor, onError, onLoadingChange])

  const startOrStopRecording = useCallback(async (): Promise<void> => {
    if (!window.api) {
      onError('Not running in Electron')
      return
    }

    setIsRecordingLoading(true)
    onError(null)

    try {
      if (!isRecording) {
        const sourcesResult = await window.api.getSources()
        if (!sourcesResult.ok) {
          onError(sourcesResult.error)
          return
        }

        const displayResult = await window.api.getCursorDisplay()
        if (!displayResult.ok) {
          onError(displayResult.error)
          return
        }

        const source = sourcesResult.payload.find(
          (candidate) => candidate.displayId === String(displayResult.payload.id)
        )
        if (!source) {
          onError('No screen sources found.')
          return
        }

        const stream = await captureScreen(source.id)
        streamRef.current = stream

        const startResult = await window.api.startRecording()
        if (!startResult.ok) {
          resetRecordingResources()
          onError(startResult.error)
          return
        }

        const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
          ? 'video/webm;codecs=vp9'
          : 'video/webm'

        const recorder = new MediaRecorder(stream, { mimeType })
        recorderRef.current = recorder
        writePromisesRef.current = []

        recorder.ondataavailable = (event) => {
          if (!event.data || event.data.size === 0) {
            return
          }

          const writePromise = (async () => {
            const chunk = await event.data.arrayBuffer()
            const result = await window.api.pushRecordingChunk(chunk)
            if (!result.ok) {
              onError(result.error)
              throw new Error(result.error)
            }
          })()

          writePromisesRef.current.push(writePromise)
        }

        recorder.start()
        setIsRecording(true)
        return
      }

      const recorder = recorderRef.current
      if (recorder && recorder.state !== 'inactive') {
        await new Promise<void>((resolve) => {
          recorder.onstop = async () => {
            await Promise.allSettled(writePromisesRef.current)
            resolve()
          }
          recorder.stop()
        })
      }

      writePromisesRef.current = []
      streamRef.current?.getTracks().forEach((track) => track.stop())
      streamRef.current = null
      recorderRef.current = null

      const result = await window.api.finishRecording('recording.webm')
      if (result.ok) {
        loadRecordingIntoEditor(result.payload)
      } else if (result.error !== 'Save canceled') {
        onError(result.error)
      }

      setIsRecording(false)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      onError(message)
      resetRecordingResources()
      setIsRecording(false)
    } finally {
      setIsRecordingLoading(false)
    }
  }, [isRecording, loadRecordingIntoEditor, onError, resetRecordingResources])

  return {
    isRecording,
    isRecordingLoading,
    startOrStopRecording,
    importRecording,
    resetRecordingResources
  }
}
