import React, { useEffect, useState } from 'react'

interface BoundingBoxPosition {
  x: number
  y: number
  width: number
  height: number
}

export default function App(): React.JSX.Element {
  const [boundingBox, setBoundingBox] = useState<BoundingBoxPosition | undefined>(undefined)

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setBoundingBox({ x: 82, y: 570, width: 100, height: 18 })
    }, 3000)

    return () => {
      window.clearTimeout(timeoutId)
    }
  }, [])

  return (
    <div
      style={{
        position: 'relative',
        width: '100vw',
        height: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent'
      }}
    >
      {boundingBox && (
        <div
          style={{
            position: 'absolute',
            left: `${boundingBox.x}px`,
            top: `${boundingBox.y}px`,
            width: `${boundingBox.width}px`,
            height: `${boundingBox.height}px`,
            border: '2px solid #00ff99',
            boxSizing: 'border-box',
            pointerEvents: 'none'
          }}
        />
      )}
      <h1
        style={{
          color: '#ffffff',
          fontSize: '6rem',
          fontWeight: 700,
          fontFamily: 'system-ui, sans-serif',
          textShadow: '0 2px 20px rgba(0,0,0,0.5)'
        }}
      >
        Hello World
      </h1>
    </div>
  )
}
