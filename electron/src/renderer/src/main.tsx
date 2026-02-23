import './assets/main.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router'
import App from './App'
import Dashboard from './views/Dashboard'
import Annotator from './views/Annotator'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<Dashboard />} />
          <Route path="annotator" element={<Annotator />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>
)
