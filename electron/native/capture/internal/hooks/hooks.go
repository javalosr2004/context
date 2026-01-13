package hooks

import (
	"context"
	"log/slog"
	"os"
	"sync/atomic"

	hook "github.com/robotn/gohook"
)

// EventBinding represents any event registration (internal)
type EventBinding struct {
	EventType uint8
	Keys      []string
	Handler   func(hook.Event)
}

// EventConfig specifies an event type and its associated keys
type EventConfig struct {
	Type uint8
	Keys []string
}

// Option is a functional option for configuring HookManager
type Option func(*HookManager)

// WithEvent registers a handler for a single event type
func WithEvent(eventType uint8, keys []string, handler func(hook.Event)) Option {
	return func(h *HookManager) {
		h.bindings = append(h.bindings, EventBinding{
			EventType: eventType,
			Keys:      keys,
			Handler:   handler,
		})
	}
}

// WithEvents registers a handler for multiple event types with per-event keys
func WithEvents(configs []EventConfig, handler func(hook.Event)) Option {
	return func(h *HookManager) {
		for _, cfg := range configs {
			h.bindings = append(h.bindings, EventBinding{
				EventType: cfg.Type,
				Keys:      cfg.Keys,
				Handler:   handler,
			})
		}
	}
}

type HookManager struct {
	bindings []EventBinding
	stopped  atomic.Bool
}

func New(opts ...Option) *HookManager {
	h := &HookManager{}
	for _, opt := range opts {
		opt(h)
	}
	return h
}

func (h *HookManager) Start(ctx context.Context) {
	slog.Info("starting input hooks", "exit_shortcut", "ctrl+shift+q")

	// Built-in exit handler
	hook.Register(hook.KeyDown, []string{"q", "ctrl", "shift"}, func(e hook.Event) {
		slog.Info("exit shortcut pressed")
		h.stopped.Store(true)
		hook.End()
	})

	// Register all custom event bindings
	for _, eb := range h.bindings {
		hook.Register(eb.EventType, eb.Keys, eb.Handler)
	}

	// Monitor context for cancellation
	// On SIGTERM, we exit the process directly to avoid gohook race conditions
	go func() {
		<-ctx.Done()
		if h.stopped.Load() {
			return
		}
		slog.Info("context cancelled, exiting process")
		os.Exit(0)
	}()

	s := hook.Start()
	<-hook.Process(s)

	slog.Info("hooks stopped")
}
