package capture

import (
	"fmt"
	"image"
	"image/draw"
	"image/jpeg"
	"image/png"
	"log/slog"
	"os"
	"path/filepath"
	"sync/atomic"
	"time"
)

type ScreenshotService struct {
	captureLoop *CaptureLoop
	outputDir   string
	cropSize    int
	saveCount   atomic.Int64
}

func NewScreenshotService(loop *CaptureLoop, outputDir string, cropSize int) *ScreenshotService {
	return &ScreenshotService{
		captureLoop: loop,
		outputDir:   outputDir,
		cropSize:    cropSize,
	}
}

func (s *ScreenshotService) TakeScreenshot(x, y int) error {
	display := FindDisplay(x, y)
	if display == nil {
		return fmt.Errorf("no display found for coordinates (%d, %d)", x, y)
	}

	frame := s.captureLoop.GetFrame(display.ID)
	if frame == nil {
		return fmt.Errorf("no frame available for display %d", display.ID)
	}

	// Convert global coords to display-local coords
	localX := x - display.X
	localY := y - display.Y

	// Get actual image dimensions
	bounds := frame.Bounds()
	imgW := bounds.Max.X - bounds.Min.X
	imgH := bounds.Max.Y - bounds.Min.Y

	// Calculate scale
	scaleX := float64(imgW) / float64(display.W)
	scaleY := float64(imgH) / float64(display.H)

	// Scale local coordinates to image coordinates
	imgX := int(float64(localX) * scaleX)
	imgY := int(float64(localY) * scaleY)

	// Crop size in image pixels
	cropSize := int(float64(s.cropSize) * scaleX)
	halfCrop := cropSize / 2

	// Crop region
	cropX := max(bounds.Min.X, imgX-halfCrop)
	cropY := max(bounds.Min.Y, imgY-halfCrop)
	cropW := min(cropSize, imgW-(cropX-bounds.Min.X))
	cropH := min(cropSize, imgH-(cropY-bounds.Min.Y))

	slog.Debug("processing click",
		"display", display.ID,
		"local_x", localX, "local_y", localY,
		"img_x", imgX, "img_y", imgY,
		"crop_region", fmt.Sprintf("%dx%d+%d+%d", cropW, cropH, cropX, cropY))

	// Create cropped image
	cropped := image.NewRGBA(image.Rect(0, 0, cropW, cropH))
	draw.Draw(cropped, cropped.Bounds(), frame, image.Pt(cropX, cropY), draw.Src)

	timestamp := time.Now().UnixMilli()

	// Save full screen
	fullPath := filepath.Join(s.outputDir, fmt.Sprintf("%d_full.png", timestamp))
	if err := s.savePNG(fullPath, frame); err != nil {
		slog.Error("failed to save full screenshot", "error", err)
		return err
	}
	slog.Info("saved full screenshot", "file", fullPath)

	// Save crop
	cropPath := filepath.Join(s.outputDir, fmt.Sprintf("%d_crop.png", timestamp))
	if err := s.savePNG(cropPath, cropped); err != nil {
		slog.Error("failed to save cropped screenshot", "error", err)
		return err
	}
	slog.Info("saved cropped screenshot", "file", cropPath, "click_x", x, "click_y", y)

	s.saveCount.Add(1)
	return nil
}

func (s *ScreenshotService) saveJPEG(path string, img image.Image, quality int) error {
	if quality < 0 || quality > 100 {
		return fmt.Errorf("quality must be between 0 and 100, got %d", quality)
	}
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return jpeg.Encode(f, img, &jpeg.Options{Quality: quality})
}

func (s *ScreenshotService) savePNG(path string, img image.Image) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return png.Encode(f, img)
}

func (s *ScreenshotService) SaveCount() int64 {
	return s.saveCount.Load()
}
