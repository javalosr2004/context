package main

import (
	"fmt"
	"image"
	"image/png"
	"log/slog"
	"os"
	"sync"
	"time"

	"github.com/go-vgo/robotgo"
	hook "github.com/robotn/gohook"
)

func init() {
	// Set log level based on DEBUG env var
	level := slog.LevelInfo
	if os.Getenv("DEBUG") != "" {
		level = slog.LevelDebug
	}

	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{
		Level: level,
	}))
	slog.SetDefault(logger)
}

// Display info
type DisplayInfo struct {
	ID      int
	X, Y    int     // Display position in global coords
	W, H    int     // Display size in points
	Scale   float64 // Scale factor (2.0 for Retina)
}

// Frame buffer for instant capture (per display)
var (
	latestFrames map[int]image.Image // displayID -> frame
	frameMutex   sync.RWMutex
	displays     []DisplayInfo
)

func main() {
	// Initialize display info
	latestFrames = make(map[int]image.Image)
	numDisplays := robotgo.DisplaysNum()
	slog.Info("detected displays", "count", numDisplays)

	for i := 0; i < numDisplays; i++ {
		x, y, w, h := robotgo.GetDisplayBounds(i)
		scale := robotgo.ScaleF(i)
		displays = append(displays, DisplayInfo{
			ID: i, X: x, Y: y, W: w, H: h, Scale: scale,
		})
		slog.Debug("display info", "id", i, "x", x, "y", y, "w", w, "h", h, "scale", scale)
	}

	// Start continuous frame capture for all displays
	go captureLoop()

	// Wait a moment for first frames to be captured
	time.Sleep(100 * time.Millisecond)

	add()
}

// Continuously captures all screens and stores the latest frames
func captureLoop() {
	for {
		frameMutex.Lock()
		for _, d := range displays {
			// CaptureScreen with 5 args: x, y, w, h, displayId
			bitmap := robotgo.CaptureScreen(0, 0, d.W, d.H, d.ID)
			img := robotgo.ToImage(bitmap)
			robotgo.FreeBitmap(bitmap)
			latestFrames[d.ID] = img
		}
		frameMutex.Unlock()

		time.Sleep(16 * time.Millisecond) // ~60 fps
	}
}

// Find which display contains the given global coordinates
func findDisplay(x, y int) *DisplayInfo {
	for i := range displays {
		d := &displays[i]
		if x >= d.X && x < d.X+d.W && y >= d.Y && y < d.Y+d.H {
			return d
		}
	}
	// Fallback to first display
	if len(displays) > 0 {
		return &displays[0]
	}
	return nil
}

// Instantly saves a crop of the latest buffered frame
func takeScreenshot(x, y int) {
	// Find which display the click is on
	d := findDisplay(x, y)
	if d == nil {
		slog.Warn("no display found for coordinates", "x", x, "y", y)
		return
	}

	frameMutex.RLock()
	frame := latestFrames[d.ID]
	frameMutex.RUnlock()

	if frame == nil {
		slog.Warn("no frame available yet", "display", d.ID)
		return
	}

	// Convert global coords to display-local coords
	localX := x - d.X
	localY := y - d.Y

	// Get actual image dimensions
	bounds := frame.Bounds()
	imgW := bounds.Max.X - bounds.Min.X
	imgH := bounds.Max.Y - bounds.Min.Y

	// Calculate scale from actual image vs display size
	scaleX := float64(imgW) / float64(d.W)
	scaleY := float64(imgH) / float64(d.H)

	slog.Debug("processing click",
		"display", d.ID,
		"local_x", localX, "local_y", localY,
		"img_w", imgW, "img_h", imgH,
		"scale_x", scaleX, "scale_y", scaleY)

	// Scale local coordinates to image coordinates
	imgX := int(float64(localX) * scaleX)
	imgY := int(float64(localY) * scaleY)

	// Crop size in image pixels (200 points * scale)
	cropSize := int(200 * scaleX)
	halfCrop := cropSize / 2

	// Crop the region around click (in image coordinates)
	cropX := max(bounds.Min.X, imgX-halfCrop)
	cropY := max(bounds.Min.Y, imgY-halfCrop)
	cropW := min(cropSize, imgW-(cropX-bounds.Min.X))
	cropH := min(cropSize, imgH-(cropY-bounds.Min.Y))

	slog.Debug("crop region",
		"img_x", imgX, "img_y", imgY,
		"crop_x", cropX, "crop_y", cropY,
		"crop_w", cropW, "crop_h", cropH)

	// Create cropped image
	cropped := image.NewRGBA(image.Rect(0, 0, cropW, cropH))
	for dy := 0; dy < cropH; dy++ {
		for dx := 0; dx < cropW; dx++ {
			cropped.Set(dx, dy, frame.At(cropX+dx, cropY+dy))
		}
	}

	timestamp := time.Now().UnixMilli()

	// Save full screen capture
	fullFilename := fmt.Sprintf("images/%d_full.png", timestamp)
	if fullFile, err := os.Create(fullFilename); err != nil {
		slog.Error("failed to create file", "filename", fullFilename, "error", err)
	} else {
		png.Encode(fullFile, frame)
		fullFile.Close()
		slog.Info("saved full screenshot", "file", fullFilename)
	}

	// Save cropped version
	cropFilename := fmt.Sprintf("images/%d_crop.png", timestamp)
	if cropFile, err := os.Create(cropFilename); err != nil {
		slog.Error("failed to create file", "filename", cropFilename, "error", err)
	} else {
		png.Encode(cropFile, cropped)
		cropFile.Close()
		slog.Info("saved cropped screenshot", "file", cropFilename, "click_x", x, "click_y", y)
	}
}

func add() {
	slog.Info("hook started", "exit", "ctrl+shift+q")
	hook.Register(hook.KeyDown, []string{"q", "ctrl", "shift"}, func(e hook.Event) {
		slog.Info("exiting")
		hook.End()
	})

	hook.Register(hook.MouseDown, []string{}, func(e hook.Event) {
		slog.Debug("click detected", "x", e.X, "y", e.Y)
		takeScreenshot(int(e.X), int(e.Y))
	})

	// hook.Register(hook.MouseMove, []string{}, func(e hook.Event){
	// 	fmt.Println("mouseMove: ", e.X, e.Y)
	// })
	
	// hook.Register(hook.KeyDown, []string{}, func(e hook.Event) {
	// 	keyChar := hook.RawcodetoKeychar(e.Rawcode);
	// 	fmt.Println("keyDown: ", keyChar);
	// })

	s := hook.Start()
	<-hook.Process(s)
}

