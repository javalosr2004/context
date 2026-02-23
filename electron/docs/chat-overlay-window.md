# Chat Overlay Window

Sticky, always-on-top chat panel pinned to the side of the screen.
Uses a second `BrowserWindow` routed via `HashRouter` to `#/chat`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Main Window (BrowserWindow)        Chat Window (BrowserWindow)  │
│  ┌───────────────────────┐          ┌──────────┐                 │
│  │  #/ Annotator          │          │ #/chat   │ alwaysOnTop     │
│  │                        │          │          │ frame: false     │
│  │                        │          │          │ transparent      │
│  │                        │          │          │ vibrancy:sidebar │
│  └───────────────────────┘          └──────────┘                 │
│         ▲                                ▲                       │
│         └──── ipcMain (relay) ───────────┘                       │
└─────────────────────────────────────────────────────────┘
```

Both windows share the same preload and renderer bundle.
The chat window loads `index.html#/chat` which `HashRouter` resolves to `<ChatView />`.

---

## Files to create / modify

| File | Action |
|------|--------|
| `src/main/chatWindow.ts` | **Create** |
| `src/main/index.ts` | Modify — add IPC handlers, import chatWindow |
| `src/shared/types.ts` | Modify — add `ChatMessage` |
| `src/preload/index.ts` | Modify — add chat API methods |
| `src/preload/index.d.ts` | Modify — add type declarations |
| `src/renderer/src/main.tsx` | Modify — switch to `HashRouter`, add `/chat` route |
| `src/renderer/src/views/ChatView.tsx` | **Create** |
| `src/renderer/src/assets/chat.css` | **Create** (or add to `main.css`) |

---

## 1. Types — `src/shared/types.ts`

```ts
export interface ChatMessage {
  id?: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number // ms since UTC epoch
}
```

---

## 2. Main Process — `src/main/chatWindow.ts`

### Imports

```ts
import { BrowserWindow, screen } from 'electron'
import { join } from 'path'
import { is } from '@electron-toolkit/utils'
import log from './logger'
```

### Types

```ts
export interface ChatWindowOptions {
  width?: number   // default 360
  margin?: number  // px from screen edge, default 16
  side?: 'right' | 'left'
}
```

### Functions

```ts
/**
 * Create the chat overlay window pinned to the screen edge.
 * Positions itself in the workArea (avoids menu bar / dock).
 */
export function createChatWindow(opts?: ChatWindowOptions): BrowserWindow

/**
 * Get the current chat window instance (or null if closed).
 */
export function getChatWindow(): BrowserWindow | null

/**
 * Show/hide the chat window. Creates it if it doesn't exist.
 */
export function toggleChatWindow(opts?: ChatWindowOptions): void

/**
 * Close and dispose the chat window.
 */
export function destroyChatWindow(): void
```

### Full implementation

```ts
let chatWindow: BrowserWindow | null = null

export function createChatWindow(opts: ChatWindowOptions = {}): BrowserWindow {
  const { width = 360, margin = 16, side = 'right' } = opts

  const primaryDisplay = screen.getPrimaryDisplay()
  const { width: screenW, height: screenH } = primaryDisplay.workAreaSize
  const { x: workX, y: workY } = primaryDisplay.workArea

  const winHeight = screenH - margin * 2
  const winX =
    side === 'right'
      ? workX + screenW - width - margin
      : workX + margin
  const winY = workY + margin

  chatWindow = new BrowserWindow({
    width,
    height: winHeight,
    x: winX,
    y: winY,
    alwaysOnTop: true,
    frame: false,
    transparent: true,
    resizable: false,
    movable: true,
    skipTaskbar: true,
    hasShadow: true,
    vibrancy: 'sidebar',
    visualEffectState: 'active',
    webPreferences: {
      preload: join(__dirname, '../preload/index.mjs'),
      sandbox: false
    }
  })

  // 'floating' keeps it above normal windows but below screen-saver level
  chatWindow.setAlwaysOnTop(true, 'floating')

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    chatWindow.loadURL(`${process.env['ELECTRON_RENDERER_URL']}#/chat`)
  } else {
    chatWindow.loadFile(join(__dirname, '../renderer/index.html'), {
      hash: '/chat'
    })
  }

  chatWindow.on('closed', () => {
    chatWindow = null
  })

  log.info('Chat window created', { width, side })
  return chatWindow
}

export function getChatWindow(): BrowserWindow | null {
  return chatWindow
}

export function toggleChatWindow(opts?: ChatWindowOptions): void {
  if (chatWindow && !chatWindow.isDestroyed()) {
    chatWindow.isVisible() ? chatWindow.hide() : chatWindow.show()
  } else {
    createChatWindow(opts)
  }
}

export function destroyChatWindow(): void {
  if (chatWindow && !chatWindow.isDestroyed()) {
    chatWindow.close()
    chatWindow = null
  }
}
```

---

## 3. IPC Handlers — add to `src/main/index.ts`

### Imports to add

```ts
import { toggleChatWindow, getChatWindow, destroyChatWindow } from './chatWindow'
import type { ChatMessage } from '../shared/types'
```

### Handlers (inside `app.whenReady().then`)

```ts
ipcMain.handle('chat:toggle', async (): Promise<Result<null>> => {
  toggleChatWindow()
  return Ok(null)
})

ipcMain.handle('chat:destroy', async (): Promise<Result<null>> => {
  destroyChatWindow()
  return Ok(null)
})

ipcMain.handle('chat:send-message', async (_event, message: string): Promise<Result<null>> => {
  const chatWin = getChatWindow()
  if (!chatWin || chatWin.isDestroyed()) {
    return Err('Chat window not open')
  }
  chatWin.webContents.send('chat:new-message', {
    role: 'user',
    content: message,
    timestamp: Date.now()
  } satisfies ChatMessage)
  return Ok(null)
})
```

---

## 4. Preload — add to `src/preload/index.ts`

### Import to add

```ts
import type { ChatMessage } from '../shared/types'
```

### Methods to add to the `api` object

```ts
toggleChat: (): Promise<Result<null>> =>
  ipcRenderer.invoke('chat:toggle'),

destroyChat: (): Promise<Result<null>> =>
  ipcRenderer.invoke('chat:destroy'),

sendChatMessage: (message: string): Promise<Result<null>> =>
  ipcRenderer.invoke('chat:send-message', message),

onChatMessage(callback: (msg: ChatMessage) => void): Unsubscribe {
  const handler = (_event: Electron.IpcRendererEvent, msg: ChatMessage): void => {
    callback(msg)
  }
  ipcRenderer.on('chat:new-message', handler)
  return () => {
    ipcRenderer.removeListener('chat:new-message', handler)
  }
},
```

---

## 5. Preload types — `src/preload/index.d.ts`

Add these to your existing `Api` interface (or whatever declares `window.api`):

```ts
toggleChat: () => Promise<Result<null>>
destroyChat: () => Promise<Result<null>>
sendChatMessage: (message: string) => Promise<Result<null>>
onChatMessage: (callback: (msg: ChatMessage) => void) => () => void
```

---

## 6. Router — `src/renderer/src/main.tsx`

Switch from `BrowserRouter` to `HashRouter` and add the `/chat` route.

> **Why HashRouter?** `BrowserWindow.loadFile()` uses `file://` protocol.
> Path-based routing doesn't work with `file://`. Hash routing (`#/chat`) does.

### Imports

```tsx
import { HashRouter, Route, Routes } from 'react-router'
import App from './App'
import Annotator from './views/Annotator'
import ChatView from './views/ChatView'
```

### Render

```tsx
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <HashRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<Annotator />} />
        </Route>
        <Route path="/chat" element={<ChatView />} />
      </Routes>
    </HashRouter>
  </StrictMode>
)
```

Note: `/chat` is **outside** the `<App />` layout so it gets its own full-page layout with no shared chrome.

---

## 7. Chat View — `src/renderer/src/views/ChatView.tsx`

### Imports

```tsx
import { useState, useEffect, useRef } from 'react'
import type { ChatMessage } from '../../../shared/types'
```

### Component

```tsx
export default function ChatView(): React.JSX.Element {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  // Listen for messages relayed from main process
  useEffect(() => {
    const unsub = window.api.onChatMessage((msg: ChatMessage) => {
      setMessages((prev) => [...prev, msg])
    })
    return unsub
  }, [])

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = (): void => {
    const text = input.trim()
    if (!text) return

    const msg: ChatMessage = {
      role: 'user',
      content: text,
      timestamp: Date.now()
    }
    setMessages((prev) => [...prev, msg])
    window.api.sendChatMessage(text)
    setInput('')
  }

  const handleKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-root">
      <div className="chat-titlebar">Chat</div>

      <div className="chat-messages">
        {messages.map((m, i) => (
          <div key={i} className={`chat-bubble ${m.role}`}>
            {m.content}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-bar">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message..."
        />
        <button onClick={handleSend}>Send</button>
      </div>
    </div>
  )
}
```

---

## 8. CSS — `src/renderer/src/assets/chat.css`

Import this in `ChatView.tsx` or in `main.tsx` globally.

```css
/*
 * html/body must be transparent for BrowserWindow({ transparent: true })
 * Scope to #/chat route to avoid affecting main window.
 * If using a global import, the vibrancy handles the background on macOS
 * so this only matters for the chat window.
 */

.chat-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  border-radius: 12px;
  overflow: hidden;
  background: transparent;
  color: #f0f0f0;
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif;
  font-size: 13px;
}

/* --- Draggable title bar --- */
.chat-titlebar {
  -webkit-app-region: drag;
  padding: 14px 16px 10px;
  font-weight: 600;
  font-size: 13px;
  letter-spacing: 0.02em;
  user-select: none;
  flex-shrink: 0;
}

.chat-titlebar button {
  -webkit-app-region: no-drag;
}

/* --- Message area --- */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 4px 12px 8px;
}

.chat-messages::-webkit-scrollbar {
  width: 6px;
}

.chat-messages::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.15);
  border-radius: 3px;
}

/* --- Bubbles --- */
.chat-bubble {
  padding: 8px 12px;
  border-radius: 10px;
  margin-bottom: 6px;
  max-width: 85%;
  line-height: 1.45;
  word-wrap: break-word;
}

.chat-bubble.user {
  background: #0a84ff;
  margin-left: auto;
  border-bottom-right-radius: 4px;
}

.chat-bubble.assistant {
  background: rgba(255, 255, 255, 0.08);
  border-bottom-left-radius: 4px;
}

.chat-bubble.system {
  background: rgba(255, 200, 50, 0.1);
  color: rgba(255, 200, 50, 0.9);
  font-size: 12px;
  text-align: center;
  max-width: 100%;
}

/* --- Input bar --- */
.chat-input-bar {
  display: flex;
  padding: 8px 10px;
  gap: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  flex-shrink: 0;
}

.chat-input-bar input {
  flex: 1;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 8px 12px;
  color: #f0f0f0;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s;
}

.chat-input-bar input:focus {
  border-color: rgba(10, 132, 255, 0.5);
}

.chat-input-bar input::placeholder {
  color: rgba(255, 255, 255, 0.3);
}

.chat-input-bar button {
  background: #0a84ff;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  flex-shrink: 0;
}

.chat-input-bar button:hover {
  background: #0070e0;
}

.chat-input-bar button:active {
  background: #005cbf;
}
```

### Making the body transparent (chat window only)

The chat window needs `html, body { background: transparent }`.
Easiest approach — add this at the top of `ChatView.tsx`:

```tsx
useEffect(() => {
  document.body.style.background = 'transparent'
  document.documentElement.style.background = 'transparent'
  return () => {
    document.body.style.background = ''
    document.documentElement.style.background = ''
  }
}, [])
```

---

## 9. BrowserWindow options reference

### Constructor options used

| Option | Value | Why |
|--------|-------|-----|
| `alwaysOnTop` | `true` | Overlay stays visible |
| `frame` | `false` | No OS title bar; CSS handles titlebar |
| `transparent` | `true` | Allows rounded corners + vibrancy |
| `resizable` | `false` | Fixed panel width |
| `movable` | `true` | User can reposition by dragging titlebar |
| `skipTaskbar` | `true` | Doesn't appear in Dock |
| `hasShadow` | `true` | macOS window shadow |
| `vibrancy` | `'sidebar'` | Frosted glass effect (macOS only) |
| `visualEffectState` | `'active'` | Vibrancy stays visible even when unfocused |

### `setAlwaysOnTop` levels (macOS)

```ts
chatWindow.setAlwaysOnTop(true, level)
```

| Level | Behavior |
|-------|----------|
| `'normal'` | Above normal windows |
| `'floating'` | Above normal, below modals (recommended) |
| `'torn-off-menu'` | Above floating |
| `'modal-panel'` | Above torn-off-menu |
| `'main-menu'` | Above modal-panel |
| `'status'` | Above main-menu |
| `'pop-up-menu'` | Above status |
| `'screen-saver'` | Above everything including fullscreen apps |

### Electron `screen` module functions used

```ts
import { screen } from 'electron'

screen.getPrimaryDisplay()           // -> Display
screen.getPrimaryDisplay().workArea   // -> { x, y, width, height } (excludes dock/menubar)
screen.getPrimaryDisplay().workAreaSize // -> { width, height }
screen.getCursorScreenPoint()        // -> { x, y }
screen.getDisplayNearestPoint(point) // -> Display
screen.getAllDisplays()              // -> Display[]
```

---

## 10. Electron imports cheat sheet

### Main process

```ts
// From electron
import { BrowserWindow, screen, ipcMain, app } from 'electron'

// From your codebase
import { createChatWindow, getChatWindow, toggleChatWindow, destroyChatWindow } from './chatWindow'
import { createWindow, getMainWindow } from './window'
import { Ok, Err } from '../shared/types'
import type { Result, ChatMessage } from '../shared/types'

// From electron-toolkit
import { is } from '@electron-toolkit/utils'

// Node
import { join } from 'path'
```

### Preload

```ts
import { contextBridge, ipcRenderer } from 'electron'
import type { ChatMessage, Result } from '../shared/types'
```

### Renderer

```tsx
// React
import { useState, useEffect, useRef } from 'react'

// Router (must be HashRouter for multi-window)
import { HashRouter, Route, Routes } from 'react-router'

// Types
import type { ChatMessage } from '../../../shared/types'

// The preload-exposed API
window.api.toggleChat()
window.api.destroyChat()
window.api.sendChatMessage(text)
window.api.onChatMessage(callback) // returns unsubscribe fn
```

---

## 11. Gotchas

| Problem | Fix |
|---------|-----|
| `BrowserRouter` doesn't work in second window | Use `HashRouter` — `file://` can't do path-based routing |
| Chat window appears behind main window | Call `chatWindow.focus()` after creation or use `setAlwaysOnTop(true, 'floating')` |
| Vibrancy doesn't render | Requires `transparent: true` on the BrowserWindow. macOS only. |
| Click passes through transparent areas | Expected. If you need the whole rect to catch clicks, use a semi-transparent CSS background instead of full transparency |
| Window resets position on show/hide | `hide()` / `show()` preserves position. `close()` + recreate does not unless you save bounds. |
| Titlebar not draggable | CSS `-webkit-app-region: drag` on the titlebar div. Buttons inside must be `-webkit-app-region: no-drag`. |
| Body background bleeds through | Set `document.body.style.background = 'transparent'` in the chat view's `useEffect` |
| Second window gets wrong CSS | Both windows load the same CSS bundle. Scope chat styles under `.chat-root`. |

---

## 12. Implementation order

1. `src/shared/types.ts` — add `ChatMessage`
2. `src/main/chatWindow.ts` — create file
3. `src/main/index.ts` — add IPC handlers + imports
4. `src/preload/index.ts` — add chat methods to `api`
5. `src/preload/index.d.ts` — add type declarations
6. `src/renderer/src/main.tsx` — swap to `HashRouter`, add `/chat` route
7. `src/renderer/src/views/ChatView.tsx` — create file
8. `src/renderer/src/assets/chat.css` — create file
9. Test: `npm run dev`, then call `toggleChatWindow()` from devtools or wire a keyboard shortcut
