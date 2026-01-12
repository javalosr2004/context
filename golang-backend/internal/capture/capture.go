package capture

import (
	"context"
	"image"
	"log/slog"
	"sync"
	"sync/atomic"
	"time"

	"github.com/go-vgo/robotgo"
)

type FrameBuffer struct {
	frames map[int]image.Image
	mu     sync.RWMutex
}

type CaptureLoop struct {
	buffer       *FrameBuffer
	fps          int
	running      atomic.Bool
	captureCount atomic.Int64
	startTime    time.Time
}

func NewCaptureLoop(fps int) *CaptureLoop {
	return &CaptureLoop{
		buffer: &FrameBuffer{
			frames: make(map[int]image.Image),
		},
		fps: fps,
	}
}

func (c *CaptureLoop) Start(ctx context.Context) {
	if c.running.Swap(true) {
		return // Already running
	}

	c.startTime = time.Now()
	interval := time.Duration(1000/c.fps) * time.Millisecond
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	slog.Info("capture loop started", "fps", c.fps, "interval_ms", interval.Milliseconds())

	for {
		select {
		case <-ctx.Done():
			c.running.Store(false)
			slog.Info("capture loop stopped")
			return
		case <-ticker.C:
			c.captureFrame()
		}
	}
}

func (c *CaptureLoop) captureFrame() {
	c.buffer.mu.Lock()
	defer c.buffer.mu.Unlock()

	for _, d := range GetDisplays() {
		bitmap := robotgo.CaptureScreen(0, 0, d.W, d.H, d.ID)
		if bitmap == nil {
			continue
		}
		img := robotgo.ToImage(bitmap)
		robotgo.FreeBitmap(bitmap)
		c.buffer.frames[d.ID] = img
		c.captureCount.Add(1)
	}
}

func (c *CaptureLoop) GetFrame(displayID int) image.Image {
	c.buffer.mu.RLock()
	defer c.buffer.mu.RUnlock()
	return c.buffer.frames[displayID]
}

func (c *CaptureLoop) IsRunning() bool {
	return c.running.Load()
}

func (c *CaptureLoop) Stats() (captureCount int64, uptime time.Duration) {
	return c.captureCount.Load(), time.Since(c.startTime)
}
