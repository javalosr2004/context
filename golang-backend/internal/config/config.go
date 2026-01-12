package config

import (
	"flag"
	"os"
	"path/filepath"
)

type Config struct {
	FPS       int
	Port      int
	OutputDir string
	CropSize  int
	Debug     bool
	PprofPort int
}

var cfg *Config

func Parse() *Config {
	if cfg != nil {
		return cfg
	}

	cfg = &Config{}

	flag.IntVar(&cfg.FPS, "fps", 10, "capture frames per second")
	flag.IntVar(&cfg.Port, "port", 8765, "HTTP server port")
	flag.StringVar(&cfg.OutputDir, "output", "images", "output directory for screenshots")
	flag.IntVar(&cfg.CropSize, "crop", 200, "crop size around click in points")
	flag.IntVar(&cfg.PprofPort, "pprof", 6060, "pprof server port (0 to disable)")
	flag.Parse()

	cfg.Debug = os.Getenv("DEBUG") != ""

	// Ensure output directory exists
	if err := os.MkdirAll(cfg.OutputDir, 0755); err != nil {
		panic("failed to create output directory: " + err.Error())
	}

	// Make output dir absolute
	if !filepath.IsAbs(cfg.OutputDir) {
		if wd, err := os.Getwd(); err == nil {
			cfg.OutputDir = filepath.Join(wd, cfg.OutputDir)
		}
	}

	return cfg
}

func Get() *Config {
	if cfg == nil {
		return Parse()
	}
	return cfg
}

func (c *Config) GetFPS() int {
	return c.FPS
}

func (c *Config) GetOutputDir() string {
	return c.OutputDir
}
