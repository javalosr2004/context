import type { JSX } from 'react'

interface AnnotatorToolbarProps {
  displayName: string | null
  isLoaded: boolean
  isLoading: boolean
  isRecording: boolean
  isRecordingLoading: boolean
  hasUnsavedChanges: boolean
  onBack: () => void
  onStartOrStopRecording: () => Promise<void>
  onImport: () => Promise<void>
  onSave: () => Promise<void>
}

export function AnnotatorToolbar({
  displayName,
  isLoaded,
  isLoading,
  isRecording,
  isRecordingLoading,
  hasUnsavedChanges,
  onBack,
  onStartOrStopRecording,
  onImport,
  onSave
}: AnnotatorToolbarProps): JSX.Element {
  return (
    <div className="ann-toolbar">
      <button type="button" onClick={onBack} className="ann-btn ann-btn-ghost">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="h-4 w-4"
        >
          <polyline points="15 18 9 12 15 6" />
        </svg>
        Back
      </button>

      <div className="ann-toolbar-actions">
        {displayName && (
          <span className="font-mono text-[0.7rem] uppercase tracking-[0.12em] text-[#8d91a0]">
            {displayName}
          </span>
        )}
        <button
          type="button"
          onClick={onStartOrStopRecording}
          disabled={isRecordingLoading || isLoading}
          className={`ann-btn ${isRecording ? 'ann-btn-stop' : 'ann-btn-record'}`}
        >
          {isRecordingLoading ? (
            <span className="ann-spinner" />
          ) : isRecording ? (
            <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
              <circle cx="12" cy="12" r="6" />
            </svg>
          )}
          {isRecording ? 'Stop Recording' : 'Start Recording'}
        </button>
        <button
          type="button"
          onClick={onImport}
          disabled={isLoading || isRecording}
          className="ann-btn ann-btn-secondary"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="h-4 w-4"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          Import .ctx
        </button>
        {isLoaded && (
          <button
            type="button"
            onClick={onSave}
            disabled={!hasUnsavedChanges}
            className="ann-btn ann-btn-save"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4"
            >
              <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
              <polyline points="17 21 17 13 7 13 7 21" />
              <polyline points="7 3 7 8 15 8" />
            </svg>
            Save
          </button>
        )}
      </div>
    </div>
  )
}
