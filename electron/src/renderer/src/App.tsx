import { useEffect, useRef, useState } from 'react'

async function captureScreen(sourceId: string): Promise<MediaStream> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
      mandatory: {
        chromeMediaSource: 'desktop',
        chromeMediaSourceId: sourceId, // Use the source.id from desktopCapturer
        minWidth: 1280,
        minHeight: 720,
        maxWidth: 1920,
        maxHeight: 1080
      }
    } as MediaTrackConstraints
  })

  return stream
}

function App(): React.JSX.Element {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 })

  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const blobRef = useRef<Blob[]>([])

  useEffect(() => {
    if (!window.api) return

    // Subscribe to mouse position events from main process
    const unsubscribe = window.api.onMousePosition((position) => {
      setMousePosition(position)
    })

    return () => {
      unsubscribe()
    }
  }, [])
  // In your renderer process (App.tsx)
  const toggleCapture = async (): Promise<void> => {
    if (!window.api) {
      setError('Not running in Electron')
      return
    }

    setIsLoading(true)
    setError(null)

    if (!running) {
      window.api.startMouseTracking()

      const sourcesResult = await window.api.getSources()
      if (!sourcesResult.ok) {
        setError(sourcesResult.error)
        setIsLoading(false)
        return
      }
      const sources = sourcesResult.payload

      const displayResult = await window.api.getCursorDisplay()
      if (!displayResult.ok) {
        setError(displayResult.error)
        setIsLoading(false)
        return
      }
      const curDisplay = displayResult.payload

      let sourceId
      // TODO: Get the source matching the current display based on mouse position
      for (const source of sources) {
        if (source.displayId == String(curDisplay.id)) {
          sourceId = source.id
        }
        console.log('Source:', sourceId)
      }

      if (!sourceId) {
        setError('No screen sources found.')
        setIsLoading(false)
        return
      }

      const stream = await captureScreen(sourceId)
      streamRef.current = stream

      const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
        ? 'video/webm;codecs=vp9'
        : 'video/webm'

      const recorder = new MediaRecorder(stream, { mimeType })
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          blobRef.current.push(event.data)
        }
      }
      setRunning(true)
    } else {
      window.api.stopMouseTracking()
      setRunning(false)
    }

    setIsLoading(false)
    // try {
    // } catch (err) {
    //   setError(err instanceof Error ? err.message : String(err))
    // } finally {
    //   setIsLoading(false)
    // }
  }

  return (
    <div className="p-10 select-none">
      <div className="bg-card-bg/95 border border-card-border rounded-3xl p-12 min-w-96 text-center backdrop-blur-xl shadow-[0_4px_24px_rgba(0,0,0,0.4),0_0_80px_rgba(99,102,241,0.05)]">
        <div className="flex items-center justify-center gap-3.5 mb-4">
          <div
            className={`w-3 h-3 rounded-full transition-all duration-300 ${
              running
                ? 'bg-capture-green shadow-[0_0_12px_rgba(16,185,129,0.5),0_0_24px_rgba(16,185,129,0.3)] animate-pulse'
                : 'bg-gray-600'
            }`}
          />
          <h1 className="font-display text-3xl font-bold text-gray-50 tracking-tight">
            Screen Capture
          </h1>
        </div>

        <p className="font-sans text-sm text-gray-400 mb-8 leading-relaxed">
          {running
            ? 'Capturing screen on every click... (Ctrl+Shift+Q to quit daemon)'
            : 'Click start to begin capturing screenshots on mouse clicks'}
        </p>

        {error && (
          <p className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 mb-5 text-sm text-red-300">
            {error}
          </p>
        )}

        {/* Debug: Mouse Position */}
        <div className="bg-black/30 border border-gray-700 rounded-lg px-4 py-2 mb-5 font-mono text-xs text-gray-400">
          Mouse: <span className="text-cyan-400">x: {mousePosition.x}</span>{' '}
          <span className="text-purple-400">y: {mousePosition.y}</span>
        </div>

        <button
          className={`inline-flex items-center justify-center gap-2.5 px-10 py-4 border-none rounded-xl font-sans text-base font-semibold cursor-pointer transition-all duration-200 min-w-44 text-white disabled:opacity-70 disabled:cursor-not-allowed ${
            running
              ? 'bg-gradient-to-br from-capture-red to-red-600 shadow-[0_4px_16px_rgba(239,68,68,0.3)] hover:not-disabled:-translate-y-0.5 hover:not-disabled:shadow-[0_6px_24px_rgba(239,68,68,0.3)]'
              : 'bg-gradient-to-br from-capture-green to-emerald-600 shadow-[0_4px_16px_rgba(16,185,129,0.3)] hover:not-disabled:-translate-y-0.5 hover:not-disabled:shadow-[0_6px_24px_rgba(16,185,129,0.3)]'
          }`}
          onClick={toggleCapture}
          disabled={isLoading}
        >
          {isLoading ? (
            <span className="w-5 h-5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
          ) : running ? (
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
      </div>
    </div>
  )
}

export default App
