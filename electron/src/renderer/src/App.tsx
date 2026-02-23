import { Outlet } from 'react-router'

export default function App(): React.JSX.Element {
  return (
    <div className="flex flex-col min-h-screen w-full max-h-screen">
      <main className="flex-1 min-h-0 flex flex-col">
        <Outlet />
      </main>
    </div>
  )
}
