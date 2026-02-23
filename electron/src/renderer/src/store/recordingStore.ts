import { create } from 'zustand'

export interface RecordingState {
  /** Path to the .ctx archive file */
  archivePath: string | null
  /** Path to the extracted video file (after import) */
  videoPath: string | null
  /** Path to the extracted events.jsonl file (after import) */
  eventsPath: string | null
  /** Whether the recording has been extracted and is ready to view */
  isLoaded: boolean
}

interface RecordingActions {
  /** Set the archive path after recording finishes */
  setArchivePath: (archivePath: string) => void
  /** Set the extracted paths after import */
  setExtractedPaths: (videoPath: string, eventsPath: string) => void
  /** Clear all recording data */
  clear: () => void
}

type RecordingStore = RecordingState & RecordingActions

const initialState: RecordingState = {
  archivePath: null,
  videoPath: null,
  eventsPath: null,
  isLoaded: false
}

export const useRecordingStore = create<RecordingStore>((set) => ({
  ...initialState,

  setArchivePath: (archivePath) =>
    set({
      archivePath,
      videoPath: null,
      eventsPath: null,
      isLoaded: false
    }),

  setExtractedPaths: (videoPath, eventsPath) =>
    set({
      videoPath,
      eventsPath,
      isLoaded: true
    }),

  clear: () => set(initialState)
}))
