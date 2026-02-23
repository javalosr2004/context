import { useNavigate } from 'react-router'
import ContextCard from '../components/ContextCard'

interface ContextItem {
  id: string
  src: string
  isLocal: boolean
  title: string
  steps: number
  duration: string
  lastOpened: string
  imageSrc?: string
}

const recentContexts: ContextItem[] = [
  {
    id: '1',
    src: '/contexts/onboarding-flow',
    isLocal: true,
    title: 'Onboarding Flow',
    steps: 12,
    duration: '3m 42s',
    lastOpened: '2 hours ago'
  },
  {
    id: '2',
    src: '/contexts/deploy-staging',
    isLocal: true,
    title: 'Deploy to Staging',
    steps: 8,
    duration: '1m 15s',
    lastOpened: 'Yesterday'
  },
  {
    id: '3',
    src: '/contexts/bug-report',
    isLocal: true,
    title: 'Bug Report Triage',
    steps: 6,
    duration: '2m 08s',
    lastOpened: '3 days ago'
  }
]

const exploreContexts: ContextItem[] = [
  {
    id: '4',
    src: '/contexts/pr-review',
    isLocal: false,
    title: 'PR Review Checklist',
    steps: 10,
    duration: '4m 20s',
    lastOpened: 'Shared by team'
  },
  {
    id: '5',
    src: '/contexts/env-setup',
    isLocal: false,
    title: 'Environment Setup',
    steps: 15,
    duration: '6m 55s',
    lastOpened: 'Shared by team'
  },
  {
    id: '6',
    src: '/contexts/release',
    isLocal: false,
    title: 'Release Workflow',
    steps: 9,
    duration: '3m 10s',
    lastOpened: 'Shared by team'
  }
]

export default function Dashboard(): React.JSX.Element {
  const navigate = useNavigate()

  return (
    <div className="relative flex-1 flex flex-col overflow-y-auto overflow-x-hidden">
      {/* Noise grain overlay */}
      <div className="dash-grain" aria-hidden="true" />

      <div className="flex-1 px-12 pt-10 pb-24 max-w-[1100px] w-full mx-auto">
        {/* Header */}
        <header className="mb-11 animate-fade-up">
          <div>
            <h1 className="font-display text-[1.75rem] font-semibold tracking-[-0.03em] text-[#f0ece4] leading-[1.2]">
              Context
            </h1>
            <p className="font-sans text-[0.8125rem] text-[#6b6d7a] mt-1 tracking-[0.04em] uppercase font-medium">
              Workflow tutorials
            </p>
          </div>
        </header>

        {/* Recently Viewed */}
        <section className="mb-10 animate-fade-up" style={{ animationDelay: '60ms' }}>
          <div className="flex items-center gap-2.5 mb-4">
            <h2 className="font-display text-[1.0625rem] font-medium text-[#c4c0b6] tracking-[-0.01em]">
              Recently Viewed
            </h2>
            <span className="font-mono text-[0.6875rem] text-[#4e505c] bg-white/4 px-2 py-0.5 rounded-full font-medium">
              {recentContexts.length}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-4">
            {recentContexts.map((ctx, i) => (
              <ContextCard
                key={ctx.id}
                id={ctx.id}
                src={ctx.src}
                isLocal={ctx.isLocal}
                title={ctx.title}
                steps={ctx.steps}
                duration={ctx.duration}
                lastOpened={ctx.lastOpened}
                imageSrc={ctx.imageSrc}
                style={{ animationDelay: `${i * 80}ms` }}
              />
            ))}
          </div>
        </section>

        {/* Explore */}
        <section className="mb-10 animate-fade-up" style={{ animationDelay: '200ms' }}>
          <div className="flex items-center gap-2.5 mb-4">
            <h2 className="font-display text-[1.0625rem] font-medium text-[#c4c0b6] tracking-[-0.01em]">
              Explore
            </h2>
            <span className="font-mono text-[0.6875rem] text-[#4e505c] bg-white/4 px-2 py-0.5 rounded-full font-medium">
              {exploreContexts.length}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-4">
            {exploreContexts.map((ctx, i) => (
              <ContextCard
                key={ctx.id}
                id={ctx.id}
                src={ctx.src}
                isLocal={ctx.isLocal}
                title={ctx.title}
                steps={ctx.steps}
                duration={ctx.duration}
                lastOpened={ctx.lastOpened}
                imageSrc={ctx.imageSrc}
                style={{ animationDelay: `${150 + i * 80}ms` }}
              />
            ))}
          </div>
        </section>
      </div>

      {/* Create button */}
      <button
        className="fixed bottom-8 right-10 z-40 flex items-center gap-2 py-3 pl-5 pr-6 font-display text-sm font-medium text-[#1a1b26] bg-linear-to-br from-[#e8a84c] to-[#d4943e] border-none rounded-xl cursor-pointer tracking-[-0.01em] transition-[transform,filter] duration-200 ease-[cubic-bezier(0.22,1,0.36,1)] hover:-translate-y-0.5 hover:scale-[1.03] hover:brightness-[1.08] active:translate-y-0 active:scale-[0.98]"
        style={{
          animation:
            'dash-fade-up 0.5s ease-out 0.4s both, dash-create-glow 3s ease-in-out 1s infinite'
        }}
        onClick={() => navigate('/annotator')}
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 18 18"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        >
          <line x1="9" y1="3" x2="9" y2="15" />
          <line x1="3" y1="9" x2="15" y2="9" />
        </svg>
        Create
      </button>
    </div>
  )
}
