package logging

import (
	"log/slog"
	"os"
)

var logger *slog.Logger

func Init(debug bool) *slog.Logger {
	level := slog.LevelInfo
	if debug {
		level = slog.LevelDebug
	}

	handler := slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{
		Level:     level,
		AddSource: debug,
	})

	logger = slog.New(handler)
	slog.SetDefault(logger)

	return logger
}

func Get() *slog.Logger {
	if logger == nil {
		return Init(false)
	}
	return logger
}
