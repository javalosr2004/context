import type { JSX } from 'react'
import type { EventTooltipState } from './types'

interface EventTooltipProps {
  tooltip: EventTooltipState | null
}

export function EventTooltip({ tooltip }: EventTooltipProps): JSX.Element | null {
  if (!tooltip) {
    return null
  }

  return (
    <div
      role="tooltip"
      className="ann-event-tooltip"
      style={{
        left: tooltip.left + 12,
        top: tooltip.top + 12
      }}
    >
      x: {Math.round(tooltip.x)}, y: {Math.round(tooltip.y)}
    </div>
  )
}
