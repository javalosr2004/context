import { useState, useEffect } from 'react'

interface CaptureStatus {
  isRunning: boolean
  capturesDir: string
}

function App(): React.JSX.Element {
  const [status, setStatus] = useState<CaptureStatus>({
    isRunning: false,
    capturesDir: ''
  })
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Only run in Electron environment
    if (window.api) {
      window.api.getCaptureStatus().then(setStatus)
      const unsubscribe = window.api.onCaptureStatus(setStatus)
      return () => {
        unsubscribe()
      }
    }
  }, [])

  const toggleCapture = async (): Promise<void> => {
    if (!window.api) {
      setError('Not running in Electron')
      return
    }

    setIsLoading(true)
    setError(null)
    try {
      if (status.isRunning) {
        const result = await window.api.stopCapture()
        if (result.success && result.status) {
          setStatus(result.status)
        } else if (result.error) {
          setError(result.error)
        }
      } else {
        const result = await window.api.startCapture()
        if (result.success && result.status) {
          setStatus(result.status)
        } else if (result.error) {
          setError(result.error)
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="p-10 select-none">
      <div className="bg-card-bg/95 border border-card-border rounded-3xl p-12 min-w-96 text-center backdrop-blur-xl shadow-[0_4px_24px_rgba(0,0,0,0.4),0_0_80px_rgba(99,102,241,0.05)]">
        <div className="flex items-center justify-center gap-3.5 mb-4">
          <div
            className={`w-3 h-3 rounded-full transition-all duration-300 ${
              status.isRunning
                ? 'bg-capture-green shadow-[0_0_12px_rgba(16,185,129,0.5),0_0_24px_rgba(16,185,129,0.3)] animate-pulse'
                : 'bg-gray-600'
            }`}
          />
          <h1 className="font-display text-3xl font-bold text-gray-50 tracking-tight">
            Screen Capture
          </h1>
        </div>

        <p className="font-sans text-sm text-gray-400 mb-8 leading-relaxed">
          {status.isRunning
            ? 'Capturing screen on every click... (Ctrl+Shift+Q to quit daemon)'
            : 'Click start to begin capturing screenshots on mouse clicks'}
        </p>

        {error && (
          <p className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 mb-5 text-sm text-red-300">
            {error}
          </p>
        )}

        <button
          className={`inline-flex items-center justify-center gap-2.5 px-10 py-4 border-none rounded-xl font-sans text-base font-semibold cursor-pointer transition-all duration-200 min-w-44 text-white disabled:opacity-70 disabled:cursor-not-allowed ${
            status.isRunning
              ? 'bg-gradient-to-br from-capture-red to-red-600 shadow-[0_4px_16px_rgba(239,68,68,0.3)] hover:not-disabled:-translate-y-0.5 hover:not-disabled:shadow-[0_6px_24px_rgba(239,68,68,0.3)]'
              : 'bg-gradient-to-br from-capture-green to-emerald-600 shadow-[0_4px_16px_rgba(16,185,129,0.3)] hover:not-disabled:-translate-y-0.5 hover:not-disabled:shadow-[0_6px_24px_rgba(16,185,129,0.3)]'
          }`}
          onClick={toggleCapture}
          disabled={isLoading}
        >
          {isLoading ? (
            <span className="w-5 h-5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
          ) : status.isRunning ? (
            <>
              <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
              Stop Capture
            </>
          ) : (
            <>
              <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
                <path d="M8 5v14l11-7z" />
              </svg>
              Start Capture
            </>
          )}
        </button>

        {status.capturesDir && (
          <p className="mt-6 text-xs text-gray-500">
            <span className="block mb-1.5">Saves to:</span>
            <code className="inline-block bg-black/30 px-3 py-1.5 rounded-md font-mono text-xs text-gray-400 max-w-72 overflow-hidden text-ellipsis whitespace-nowrap">
              {status.capturesDir}
            </code>
          </p>
        )}
      </div>
    </div>
  )
}

export default App
