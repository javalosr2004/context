package llm

import (
	"fmt"
	"os"
	"time"
)

const (
	DefaultModel   = "gemini-2.5-flash-preview-05-20"
	DefaultBaseURL = "https://generativelanguage.googleapis.com/v1beta/models"
	DefaultTimeout = 60 * time.Second
)

type Config struct {
	APIKey  string
	Model   string
	BaseURL string
	Timeout time.Duration
}

func FromEnv() Config {
	return Config{
		APIKey:  os.Getenv("GEMINI_API_KEY"),
		Model:   envOrDefault("GEMINI_MODEL", DefaultModel),
		BaseURL: envOrDefault("GEMINI_BASE_URL", DefaultBaseURL),
		Timeout: DefaultTimeout,
	}
}

func (c Config) Validate() error {
	if c.APIKey == "" {
		return fmt.Errorf("GEMINI_API_KEY is required")
	}
	return nil
}

func envOrDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
