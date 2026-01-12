package server

import (
	"encoding/json"
	"net/http"
	"time"
)

type StatusProvider interface {
	IsRunning() bool
	Stats() (captureCount int64, uptime time.Duration)
}

type ConfigProvider interface {
	GetFPS() int
	GetOutputDir() string
}

type Handlers struct {
	status StatusProvider
	config ConfigProvider
}

func NewHandlers(status StatusProvider, config ConfigProvider) *Handlers {
	return &Handlers{
		status: status,
		config: config,
	}
}

func (h *Handlers) Health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status": "ok",
		"time":   time.Now().Unix(),
	})
}

func (h *Handlers) Status(w http.ResponseWriter, r *http.Request) {
	captureCount, uptime := h.status.Stats()

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"running":      h.status.IsRunning(),
		"fps":          h.config.GetFPS(),
		"captureCount": captureCount,
		"uptime":       uptime.Seconds(),
		"outputDir":    h.config.GetOutputDir(),
	})
}

func (h *Handlers) Config(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"fps":       h.config.GetFPS(),
		"outputDir": h.config.GetOutputDir(),
	})
}
