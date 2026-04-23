import type { JSX, MouseEvent as ReactMouseEvent } from 'react'
import { DEFAULT_SELECTED, nodeLabel } from './model'
import type { AnnotatorEvent, LabelField, SnapView } from './types'

interface AnnotatorSidebarProps {
  sortedEvents: AnnotatorEvent[]
  currentTimeMs: number
  activeEventIdx: number | null
  expandedEventIdx: number | null
  activeSnapshot: SnapView | null
  activeNodeKey: string
  isEditingBbox: boolean
  formatTimestamp: (ms: number) => string
  onCollapseTree: () => void
  onStopEditingBbox: () => void
  onStartCustomAnnotation: () => void
  onSelectNode: (nodeKey: string) => void
  onUpdateLabel: (field: LabelField, value: string) => void
  onEventClick: (timestampMs: number, index: number) => void
  onEventDoubleClick: (timestampMs: number, index: number) => void
  onEventHoverEnter: (event: AnnotatorEvent, pointerEvent: ReactMouseEvent) => void
  onEventHoverMove: (pointerEvent: ReactMouseEvent) => void
  onEventHoverLeave: () => void
}

export function AnnotatorSidebar({
  sortedEvents,
  currentTimeMs,
  activeEventIdx,
  expandedEventIdx,
  activeSnapshot,
  activeNodeKey,
  isEditingBbox,
  formatTimestamp,
  onCollapseTree,
  onStopEditingBbox,
  onStartCustomAnnotation,
  onSelectNode,
  onUpdateLabel,
  onEventClick,
  onEventDoubleClick,
  onEventHoverEnter,
  onEventHoverMove,
  onEventHoverLeave
}: AnnotatorSidebarProps): JSX.Element {
  if (expandedEventIdx !== null && activeSnapshot) {
    const expandedEvent = sortedEvents[expandedEventIdx]

    return (
      <aside className="ann-sidebar">
        <div className="ann-sidebar-head">
          <button
            type="button"
            onClick={() => {
              onCollapseTree()
              onStopEditingBbox()
            }}
            className="ann-btn ann-btn-ghost"
            style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-3 w-3"
            >
              <polyline points="15 18 9 12 15 6" />
            </svg>
            Events
          </button>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <button
              type="button"
              onClick={isEditingBbox ? onStopEditingBbox : onStartCustomAnnotation}
              className={`ann-btn ${isEditingBbox ? 'ann-btn-save' : 'ann-btn-secondary'}`}
              style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
            >
              {isEditingBbox ? 'Done' : 'Custom Annotation'}
            </button>
            <span className="ann-sidebar-count">{formatTimestamp(expandedEvent.timestampMs)}</span>
          </div>
        </div>
        <div className="ann-sidebar-list">
          <div className="ax-tree-section">
            <div className="ax-tree-section-label">Label</div>
            <input
              type="text"
              className="ann-label-input"
              value={activeSnapshot.title ?? ''}
              placeholder={expandedEvent.eventName}
              onChange={(event) => onUpdateLabel('title', event.target.value)}
              aria-label="Event title"
            />
            <textarea
              className="ann-label-textarea"
              value={activeSnapshot.description ?? ''}
              placeholder={
                expandedEvent.x !== undefined && expandedEvent.y !== undefined
                  ? `(${Math.round(expandedEvent.x)}, ${Math.round(expandedEvent.y)})`
                  : 'description'
              }
              onChange={(event) => onUpdateLabel('description', event.target.value)}
              rows={2}
              aria-label="Event description"
            />
          </div>

          <div className="ax-tree-section">
            <div className="ax-tree-section-label">Hit Target</div>
            <div
              className={`ax-tree-node ${activeNodeKey === DEFAULT_SELECTED ? 'ax-tree-node-active' : ''}`}
              onClick={() => onSelectNode(DEFAULT_SELECTED)}
            >
              <span className="ax-tree-node-role">{activeSnapshot.current?.axRole}</span>
              <span className="ax-tree-node-text">
                {activeSnapshot.current ? nodeLabel(activeSnapshot.current) : ''}
              </span>
              {activeSnapshot.current?.boundingBox && (
                <span className="ax-tree-node-bbox">bbox</span>
              )}
            </div>
          </div>

          {(activeSnapshot.parents?.length ?? 0) > 0 && (
            <div className="ax-tree-section">
              <div className="ax-tree-section-label">
                Parents ({activeSnapshot.parents?.length ?? 0})
              </div>
              {activeSnapshot.parents?.map((node, index) => {
                const key = `parents:${index}`
                return (
                  <div
                    key={key}
                    className={`ax-tree-node ${activeNodeKey === key ? 'ax-tree-node-active' : ''}`}
                    style={{ paddingLeft: `${0.75 + index * 0.5}rem` }}
                    onClick={() => onSelectNode(key)}
                  >
                    <span className="ax-tree-node-role">{node.axRole}</span>
                    <span className="ax-tree-node-text">{nodeLabel(node)}</span>
                    {node.boundingBox && <span className="ax-tree-node-bbox">bbox</span>}
                  </div>
                )
              })}
            </div>
          )}

          {activeSnapshot.userOverride && (
            <div className="ax-tree-section">
              <div className="ax-tree-section-label">Override</div>
              <div
                className={`ax-tree-node ${activeNodeKey === 'user_override' ? 'ax-tree-node-active' : ''}`}
                onClick={() => onSelectNode('user_override')}
              >
                <span className="ax-tree-node-role">custom</span>
                <span className="ax-tree-node-text">user-drawn region</span>
                <span className="ax-tree-node-bbox">bbox</span>
              </div>
            </div>
          )}

          {(activeSnapshot.children?.length ?? 0) > 0 && (
            <div className="ax-tree-section">
              <div className="ax-tree-section-label">
                Children ({activeSnapshot.children?.length ?? 0})
              </div>
              {activeSnapshot.children?.map((node, index) => {
                const key = `children:${index}`
                return (
                  <div
                    key={key}
                    className={`ax-tree-node ${activeNodeKey === key ? 'ax-tree-node-active' : ''}`}
                    onClick={() => onSelectNode(key)}
                  >
                    <span className="ax-tree-node-role">{node.axRole}</span>
                    <span className="ax-tree-node-text">{nodeLabel(node)}</span>
                    {node.boundingBox && <span className="ax-tree-node-bbox">bbox</span>}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </aside>
    )
  }

  return (
    <aside className="ann-sidebar">
      <div className="ann-sidebar-head">
        <h2 className="ann-sidebar-title">Events</h2>
        <span className="ann-sidebar-count">{sortedEvents.length}</span>
      </div>
      <div className="ann-sidebar-list">
        {sortedEvents.length === 0 ? (
          <div className="ann-sidebar-empty">No events yet</div>
        ) : (
          <ul>
            {sortedEvents.map((event, index) => (
              <li
                key={`${event.timestampMs}-${event.eventName}-${index}`}
                onClick={() => onEventClick(event.timestampMs, index)}
                onDoubleClick={() => onEventDoubleClick(event.timestampMs, index)}
                onMouseEnter={(pointerEvent) => onEventHoverEnter(event, pointerEvent)}
                onMouseMove={onEventHoverMove}
                onMouseLeave={onEventHoverLeave}
                className={`ann-event ${
                  event.timestampMs <= currentTimeMs ? 'ann-event-past' : ''
                } ${activeEventIdx === index ? 'ann-event-selected' : ''}`}
              >
                <span className="ann-event-dot" />
                <div className="ann-event-info">
                  <span className="ann-event-name">{event.title}</span>
                  <span className="ann-event-time">{formatTimestamp(event.timestampMs)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  )
}
