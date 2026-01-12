package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/javalosr2004/context.git/internal/logging"
	"github.com/javalosr2004/context.git/internal/orchestrator"
)

func main() {
	// Initialize logging
	logging.Init(true)
	slog.Info("starting orchestrator")

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

	// Create and start orchestrator
	orch := orchestrator.New(orchestrator.Config{
		CapturePort:    8765,
		CaptureBinPath: "./capture", // Path to capture binary
	})

	if err := orch.Start(ctx); err != nil {
		slog.Error("orchestrator failed", "error", err)
		os.Exit(1)
	}

	// Wait for shutdown
	<-ctx.Done()
	slog.Info("orchestrator shutting down")
	orch.Stop()
	slog.Info("orchestrator stopped")
}
