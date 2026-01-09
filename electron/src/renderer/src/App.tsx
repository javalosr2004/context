import { useState } from 'react'

function App(): React.JSX.Element {
  const [result, setResult] = useState<unknown>(null)

  const ping = async (): Promise<void> => {
    const res = await window.api.rustInvoke('ping')
    setResult(res)
  }

  const echo = async (): Promise<void> => {
    const res = await window.api.rustInvoke('echo', { hello: 'world', time: Date.now() })
    setResult(res)
  }

  return (
    <div className="container">
      <h1>Rust + Electron + React</h1>
      <div className="actions">
        <button onClick={ping}>Ping Rust</button>
        <button onClick={echo}>Echo Test</button>
      </div>
      <pre className="output">
        {result ? JSON.stringify(result, null, 2) : 'Click a button to communicate with Rust...'}
      </pre>
    </div>
  )
}

export default App
