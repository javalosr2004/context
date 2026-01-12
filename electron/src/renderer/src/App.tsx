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
    window.api.getCaptureStatus().then(setStatus)

    const unsubscribe = window.api.onCaptureStatus(setStatus)

    return () => {
      unsubscribe()
    }
  }, [])

  const toggleCapture = async (): Promise<void> => {
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
    <div className="capture-app">
      <div className="capture-card">
        <div className="capture-header">
          <div className={`status-indicator ${status.isRunning ? 'active' : 'inactive'}`} />
          <h1>Screen Capture</h1>
        </div>

        <p className="capture-description">
          {status.isRunning
            ? 'Capturing screen on every click... (Ctrl+Shift+Q to quit daemon)'
            : 'Click start to begin capturing screenshots on mouse clicks'}
        </p>

        {error && <p className="error-message">{error}</p>}

        <button
          className={`capture-button ${status.isRunning ? 'stop' : 'start'}`}
          onClick={toggleCapture}
          disabled={isLoading}
        >
          {isLoading ? (
            <span className="loading-spinner" />
          ) : status.isRunning ? (
            <>
              <svg viewBox="0 0 24 24" fill="currentColor" className="button-icon">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
              Stop Capture
            </>
          ) : (
            <>
              <svg viewBox="0 0 24 24" fill="currentColor" className="button-icon">
                <path d="M8 5v14l11-7z" />
              </svg>
              Start Capture
            </>
          )}
        </button>

        {status.capturesDir && (
          <p className="captures-path">
            <span className="path-label">Saves to:</span>
            <code>{status.capturesDir}</code>
          </p>
        )}
      </div>
    </div>
  )
}

export default App
