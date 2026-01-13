package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	_ "net/http/pprof"
	"os"
	"os/signal"
	"runtime"
	"syscall"
	"time"

	hook "github.com/robotn/gohook"

	"github.com/javalosr2004/context.git/internal/capture"
	"github.com/javalosr2004/context.git/internal/config"
	"github.com/javalosr2004/context.git/internal/hooks"
	"github.com/javalosr2004/context.git/internal/logging"
	"github.com/javalosr2004/context.git/internal/server"
)

func main() {
	// Parse configuration
	cfg := config.Parse()

	// Initialize logging
	logging.Init(cfg.Debug)
	slog.Info("starting capture service",
		"fps", cfg.FPS,
		"port", cfg.Port,
		"output", cfg.OutputDir)

	// Create cancellation context
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle shutdown signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		sig := <-sigChan
		slog.Info("received shutdown signal", "signal", sig)
		cancel()
	}()

	// Start pprof server if enabled
	if cfg.PprofPort > 0 {
		go func() {
			addr := fmt.Sprintf("localhost:%d", cfg.PprofPort)
			slog.Debug("pprof server starting", "addr", addr)
			http.ListenAndServe(addr, nil)
		}()
	}

	// Initialize displays
	capture.InitDisplays()

	// Create capture loop
	captureLoop := capture.NewCaptureLoop(cfg.FPS)
	go captureLoop.Start(ctx)

	// Wait for first frame
	time.Sleep(100 * time.Millisecond)

	// Create screenshot service
	screenshotSvc := capture.NewScreenshotService(captureLoop, cfg.OutputDir, cfg.CropSize)

	// Create and start HTTP server
	srv := server.New(cfg.Port)
	handlers := server.NewHandlers(captureLoop, cfg)
	srv.RegisterHandler("/health", handlers.Health)
	srv.RegisterHandler("/status", handlers.Status)
	srv.RegisterHandler("/config", handlers.Config)

	go func() {
		if err := srv.Start(); err != nil && err != http.ErrServerClosed {
			slog.Error("HTTP server error", "error", err)
		}
	}()

	// Start memory monitor
	go memoryMonitor(ctx)
	eventCfg := []hooks.EventConfig{
		{Type: hook.MouseDown, Keys: []string{}},
		{Type: hook.KeyDown, Keys: []string{"enter"}},
	}
	// Start hooks (blocking)
	hookMgr := hooks.New(
		hooks.WithEvents(eventCfg, func(e hook.Event) {
			slog.Debug("click detected", "x", e.X, "y", e.Y)
			if err := screenshotSvc.TakeScreenshot(int(e.X), int(e.Y)); err != nil {
				slog.Error("screenshot failed", "error", err)
			}
		}),
	)
	hookMgr.Start(ctx)

	// Graceful shutdown
	slog.Info("shutting down")
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer shutdownCancel()
	srv.Shutdown(shutdownCtx)
	slog.Info("shutdown complete")
}

func memoryMonitor(ctx context.Context) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			var m runtime.MemStats
			runtime.ReadMemStats(&m)
			slog.Info("memory stats",
				"alloc_mb", m.Alloc/1024/1024,
				"sys_mb", m.Sys/1024/1024,
				"num_gc", m.NumGC,
			)
		}
	}
}
