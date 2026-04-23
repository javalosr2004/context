import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent, RefObject } from 'react'
import { formatTimestamp } from './model'
import type { AnnotatorEvent, EventTooltipState } from './types'

const BBOX_WINDOW_MS = 200

interface UseAnnotatorTimelineOptions {
  events: AnnotatorEvent[]
  videoRef: RefObject<HTMLVideoElement | null>
}

interface UseAnnotatorTimelineResult {
  currentTimeMs: number
  durationMs: number
  activeEventIdx: number | null
  expandedEventIdx: number | null
  sortedEvents: AnnotatorEvent[]
  displayEventIdx: number | null
  eventTooltip: EventTooltipState | null
  resetTimelineState: () => void
  handleLoadedMetadata: () => void
  seekToTime: (timeMs: number) => void
  handleTimelineClick: (event: ReactMouseEvent<HTMLDivElement>) => void
  handleEventClick: (timestampMs: number, index: number) => void
  handleEventDoubleClick: (timestampMs: number, index: number) => void
  handleCollapseTree: () => void
  handleEventHoverEnter: (event: AnnotatorEvent, pointerEvent: ReactMouseEvent) => void
  handleEventHoverMove: (pointerEvent: ReactMouseEvent) => void
  handleEventHoverLeave: () => void
  formatTimestamp: (ms: number) => string
}

export function useAnnotatorTimeline({
  events,
  videoRef
}: UseAnnotatorTimelineOptions): UseAnnotatorTimelineResult {
  const [currentTimeMs, setCurrentTimeMs] = useState(0)
  const [durationMs, setDurationMs] = useState(120_000)
  const [manualActiveEventIdx, setManualActiveEventIdx] = useState<number | null>(null)
  const [expandedEventIdx, setExpandedEventIdx] = useState<number | null>(null)
  const [eventTooltip, setEventTooltip] = useState<EventTooltipState | null>(null)
  const rafIdRef = useRef<number | null>(null)
  const eventTooltipTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const eventTooltipPointerRef = useRef({ clientX: 0, clientY: 0 })

  const sortedEvents = useMemo(
    () => [...events].sort((left, right) => left.timestampMs - right.timestampMs),
    [events]
  )

  const clearEventTooltipTimer = useCallback((): void => {
    if (eventTooltipTimerRef.current === null) {
      return
    }

    clearTimeout(eventTooltipTimerRef.current)
    eventTooltipTimerRef.current = null
  }, [])

  const resetTimelineState = useCallback((): void => {
    setDurationMs(120_000)
    setCurrentTimeMs(0)
    setManualActiveEventIdx(null)
    setExpandedEventIdx(null)
    setEventTooltip(null)
    clearEventTooltipTimer()
  }, [clearEventTooltipTimer])

  useEffect(() => {
    const updateTime = (): void => {
      if (videoRef.current) {
        setCurrentTimeMs(videoRef.current.currentTime * 1000)
      }
      rafIdRef.current = requestAnimationFrame(updateTime)
    }

    rafIdRef.current = requestAnimationFrame(updateTime)
    return () => {
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current)
      }
    }
  }, [videoRef])

  useEffect(() => clearEventTooltipTimer, [clearEventTooltipTimer])

  const handleLoadedMetadata = useCallback((): void => {
    if (!videoRef.current) {
      return
    }

    setDurationMs(videoRef.current.duration * 1000)
  }, [videoRef])

  const seekToTime = useCallback(
    (timeMs: number): void => {
      if (!videoRef.current) {
        return
      }

      videoRef.current.currentTime = timeMs / 1000
      setCurrentTimeMs(timeMs)
    },
    [videoRef]
  )

  const handleTimelineClick = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>): void => {
      if (!videoRef.current || durationMs <= 0) {
        return
      }

      const rect = event.currentTarget.getBoundingClientRect()
      const x = event.clientX - rect.left
      const percent = Math.max(0, Math.min(1, x / rect.width))
      seekToTime(percent * durationMs)
    },
    [durationMs, seekToTime, videoRef]
  )

  const handleEventClick = useCallback(
    (timestampMs: number, index: number): void => {
      seekToTime(timestampMs)
      setManualActiveEventIdx(index)
    },
    [seekToTime]
  )

  const handleEventDoubleClick = useCallback(
    (timestampMs: number, index: number): void => {
      seekToTime(timestampMs)
      setManualActiveEventIdx(index)
      setExpandedEventIdx(index)
    },
    [seekToTime]
  )

  const handleCollapseTree = useCallback((): void => {
    setExpandedEventIdx(null)
  }, [])

  const scheduleEventTooltip = useCallback(
    (event: AnnotatorEvent): void => {
      clearEventTooltipTimer()
      if (
        event.x === undefined ||
        event.y === undefined ||
        Number.isNaN(event.x) ||
        Number.isNaN(event.y)
      ) {
        return
      }

      eventTooltipTimerRef.current = setTimeout(() => {
        eventTooltipTimerRef.current = null
        const { clientX, clientY } = eventTooltipPointerRef.current
        setEventTooltip({ x: event.x!, y: event.y!, left: clientX, top: clientY })
      }, 1000)
    },
    [clearEventTooltipTimer]
  )

  const handleEventHoverMove = useCallback((pointerEvent: ReactMouseEvent): void => {
    eventTooltipPointerRef.current = {
      clientX: pointerEvent.clientX,
      clientY: pointerEvent.clientY
    }
  }, [])

  const handleEventHoverEnter = useCallback(
    (event: AnnotatorEvent, pointerEvent: ReactMouseEvent): void => {
      eventTooltipPointerRef.current = {
        clientX: pointerEvent.clientX,
        clientY: pointerEvent.clientY
      }
      scheduleEventTooltip(event)
    },
    [scheduleEventTooltip]
  )

  const handleEventHoverLeave = useCallback((): void => {
    clearEventTooltipTimer()
    setEventTooltip(null)
  }, [clearEventTooltipTimer])

  const timeWindowEventIdx = useMemo(() => {
    let closestMatch: { index: number; distance: number } | null = null

    for (const [index, event] of sortedEvents.entries()) {
      const distance = Math.abs(event.timestampMs - currentTimeMs)
      if (distance <= BBOX_WINDOW_MS && (!closestMatch || distance < closestMatch.distance)) {
        closestMatch = { index, distance }
      }
    }

    return closestMatch?.index ?? null
  }, [currentTimeMs, sortedEvents])

  const activeEventIdx =
    manualActiveEventIdx !== null &&
    manualActiveEventIdx < sortedEvents.length &&
    Math.abs(sortedEvents[manualActiveEventIdx].timestampMs - currentTimeMs) <= BBOX_WINDOW_MS
      ? manualActiveEventIdx
      : null

  return {
    currentTimeMs,
    durationMs,
    activeEventIdx,
    expandedEventIdx,
    sortedEvents,
    displayEventIdx: activeEventIdx ?? timeWindowEventIdx,
    eventTooltip,
    resetTimelineState,
    handleLoadedMetadata,
    seekToTime,
    handleTimelineClick,
    handleEventClick,
    handleEventDoubleClick,
    handleCollapseTree,
    handleEventHoverEnter,
    handleEventHoverMove,
    handleEventHoverLeave,
    formatTimestamp
  }
}
