interface ContextCardProps {
  id: string
  src: string
  isLocal: boolean
  title: string
  steps: number
  duration: string
  lastOpened: string
  imageSrc?: string
  style?: React.CSSProperties
}

function DotPattern({ title, steps }: { title: string; steps: number }): React.JSX.Element {
  const seed = title.split('').reduce((acc, ch) => acc + ch.charCodeAt(0), 0)
  const numDots = steps

  return (
    <svg
      className="w-full h-full opacity-70 transition-opacity duration-300 group-hover:opacity-100"
      viewBox="0 0 200 100"
      fill="none"
    >
      {Array.from({ length: numDots }, (_, i) => {
        const x = 20 + (i / (numDots - 1)) * 160
        const y = 50 + Math.sin(i * 0.8 + seed * 0.1) * 20
        return (
          <circle
            key={i}
            cx={x}
            cy={y}
            r={i === 0 || i === numDots - 1 ? 4 : 2.5}
            fill={i === 0 || i === numDots - 1 ? '#e8a84c' : '#ffffff30'}
          />
        )
      })}
      {Array.from({ length: numDots - 1 }, (_, i) => {
        const x1 = 20 + (i / (numDots - 1)) * 160
        const y1 = 50 + Math.sin(i * 0.8 + seed * 0.1) * 20
        const x2 = 20 + ((i + 1) / (numDots - 1)) * 160
        const y2 = 50 + Math.sin((i + 1) * 0.8 + seed * 0.1) * 20
        return (
          <line key={`l${i}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#ffffff12" strokeWidth={1} />
        )
      })}
    </svg>
  )
}

export default function ContextCard({
  src,
  isLocal,
  title,
  steps,
  duration,
  lastOpened,
  imageSrc,
  style
}: ContextCardProps): React.JSX.Element {
  return (
    <div
      className="group cursor-pointer flex flex-col bg-[linear-gradient(165deg,#1c1d26_0%,#17181f_100%)] border border-white/6 rounded-xl overflow-hidden transition-[transform,border-color,box-shadow] duration-250 ease-[cubic-bezier(0.22,1,0.36,1)] animate-fade-up hover:-translate-y-[3px] hover:border-[rgba(232,168,76,0.2)] hover:shadow-[0_8px_32px_rgba(0,0,0,0.35),0_0_0_1px_rgba(232,168,76,0.06)] active:-translate-y-px"
      style={style}
      onClick={() => window.api.openViewer()}
      data-src={src}
    >
      {/* Thumbnail */}
      <div className="relative h-[100px] bg-linear-to-br from-[#12131a] to-[#1a1b24] border-b border-white/4 overflow-hidden">
        <div className="absolute inset-0 flex items-center justify-center p-4">
          {imageSrc ? (
            <img src={imageSrc} alt={title} className="w-full h-full object-cover rounded" />
          ) : (
            <DotPattern title={title} steps={steps} />
          )}
        </div>
      </div>

      {/* Body */}
      <div className="px-4 pt-3.5 pb-4">
        <h3 className="font-display text-[0.9375rem] font-medium text-[#e0dcd3] tracking-[-0.01em] mb-1.5 transition-colors duration-200 group-hover:text-[#f5f1e8]">
          {title}
        </h3>
        <div className="flex items-center gap-2 font-sans text-[0.75rem] text-[#5a5c68]">
          <span>
            <span className="font-mono text-[#e8a84c] font-semibold">{steps}</span> steps
          </span>
          <span
            className="inline-block w-[3px] h-[3px] rounded-full bg-[#3a3c48] shrink-0"
            aria-hidden="true"
          />
          <span>{duration}</span>
        </div>
        <p className="font-sans text-[0.6875rem] text-[#3e404c] mt-2">{lastOpened}</p>
        <div className="flex items-center gap-2 mt-2">
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${isLocal ? 'bg-emerald-500' : 'bg-[#e8a84c]'}`}
          />
          <span className="font-mono text-[0.6875rem] text-[#3e404c]">
            {isLocal ? 'Local' : 'Shared'}
          </span>
        </div>
      </div>
    </div>
  )
}
