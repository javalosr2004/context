package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"sync"
	"time"

	"github.com/javalosr2004/context.git/internal/llm"
)

type Config struct {
	CapturePort    int
	CaptureBinPath string
	LLMConfig      llm.Config
}

type CaptureStatus struct {
	Running      bool    `json:"running"`
	FPS          int     `json:"fps"`
	CaptureCount int64   `json:"captureCount"`
	Uptime       float64 `json:"uptime"`
	OutputDir    string  `json:"outputDir"`
}

type Orchestrator struct {
	cfg        Config
	captureCmd *exec.Cmd
	llmClient  *llm.Client
	httpClient *http.Client
	mu         sync.Mutex
	running    bool
}

func New(cfg Config) *Orchestrator {
	return &Orchestrator{
		cfg: cfg,
		httpClient: &http.Client{
			Timeout: 5 * time.Second,
		},
		llmClient: llm.NewClient(cfg.LLMConfig),
	}
}

// Start begins the orchestrator and starts the capture service
func (o *Orchestrator) Start(ctx context.Context) error {
	o.mu.Lock()
	defer o.mu.Unlock()

	if o.running {
		return fmt.Errorf("orchestrator already running")
	}

	// Start capture service
	if err := o.startCapture(); err != nil {
		return fmt.Errorf("failed to start capture: %w", err)
	}

	// Wait for capture service to be healthy
	if err := o.waitForHealth(ctx, 10*time.Second); err != nil {
		o.stopCapture()
		return fmt.Errorf("capture service unhealthy: %w", err)
	}

	o.running = true
	slog.Info("orchestrator started", "capturePort", o.cfg.CapturePort)

	// Start monitoring goroutine
	go o.monitor(ctx)

	return nil
}

// Stop gracefully stops the orchestrator and capture service
func (o *Orchestrator) Stop() {
	o.mu.Lock()
	defer o.mu.Unlock()

	if !o.running {
		return
	}

	o.stopCapture()
	o.running = false
	slog.Info("orchestrator stopped")
}

// GetStatus returns the current capture service status
func (o *Orchestrator) GetStatus(ctx context.Context) (*CaptureStatus, error) {
	url := fmt.Sprintf("http://localhost:%d/status", o.cfg.CapturePort)
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, err
	}

	resp, err := o.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var status CaptureStatus
	if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
		return nil, err
	}

	return &status, nil
}

// SendToLLM sends data to the configured LLM
func (o *Orchestrator) SendToLLM(ctx context.Context, prompt string, imagePaths []string) (string, error) {
	return o.llmClient.Send(ctx, prompt, imagePaths)
}

func (o *Orchestrator) startCapture() error {
	o.captureCmd = exec.Command(o.cfg.CaptureBinPath,
		"-port", fmt.Sprintf("%d", o.cfg.CapturePort),
	)
	o.captureCmd.Stdout = os.Stdout
	o.captureCmd.Stderr = os.Stderr

	if err := o.captureCmd.Start(); err != nil {
		return err
	}

	slog.Info("capture service started", "pid", o.captureCmd.Process.Pid)
	return nil
}

func (o *Orchestrator) stopCapture() {
	if o.captureCmd == nil || o.captureCmd.Process == nil {
		return
	}

	slog.Info("stopping capture service", "pid", o.captureCmd.Process.Pid)
	o.captureCmd.Process.Signal(os.Interrupt)

	// Wait with timeout
	done := make(chan error, 1)
	go func() {
		done <- o.captureCmd.Wait()
	}()

	select {
	case <-done:
		slog.Info("capture service stopped gracefully")
	case <-time.After(5 * time.Second):
		slog.Warn("capture service did not stop, killing")
		o.captureCmd.Process.Kill()
	}

	o.captureCmd = nil
}

func (o *Orchestrator) waitForHealth(ctx context.Context, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	url := fmt.Sprintf("http://localhost:%d/health", o.cfg.CapturePort)

	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
		resp, err := o.httpClient.Do(req)
		if err == nil && resp.StatusCode == http.StatusOK {
			resp.Body.Close()
			return nil
		}
		if resp != nil {
			resp.Body.Close()
		}

		time.Sleep(200 * time.Millisecond)
	}

	return fmt.Errorf("timeout waiting for health check")
}

func (o *Orchestrator) monitor(ctx context.Context) {
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			status, err := o.GetStatus(ctx)
			if err != nil {
				slog.Warn("failed to get capture status", "error", err)
				// Could implement auto-restart here
				continue
			}
			slog.Debug("capture status",
				"running", status.Running,
				"captureCount", status.CaptureCount,
				"uptime", status.Uptime,
			)
		}
	}
}
