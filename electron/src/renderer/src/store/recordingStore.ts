import { create } from 'zustand'

export interface LoadedRecording {
  recordingId: string
  displayName: string
  videoUrl: string
}

export interface RecordingState {
  /** Opaque id for the loaded recording. */
  recordingId: string | null
  /** User-facing label for the current recording. */
  displayName: string | null
  /** Main-owned media URL for the current recording. */
  videoUrl: string | null
  /** Whether a recording session is loaded in the renderer. */
  isLoaded: boolean
}

interface RecordingActions {
  /** Replace the loaded recording session metadata. */
  setLoadedRecording: (recording: LoadedRecording) => void
  /** Clear all recording data */
  clear: () => void
}

type RecordingStore = RecordingState & RecordingActions

const initialState: RecordingState = {
  recordingId: null,
  displayName: null,
  videoUrl: null,
  isLoaded: false
}

export const useRecordingStore = create<RecordingStore>((set) => ({
  ...initialState,

  setLoadedRecording: (recording) =>
    set({
      recordingId: recording.recordingId,
      displayName: recording.displayName,
      videoUrl: recording.videoUrl,
      isLoaded: true
    }),

  clear: () => set(initialState)
}))
