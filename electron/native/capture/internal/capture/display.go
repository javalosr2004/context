package capture

import (
	"log/slog"
	"sync"

	"github.com/go-vgo/robotgo"
)

type DisplayInfo struct {
	ID    int
	X, Y  int
	W, H  int
	Scale float64
}

var (
	displays     []DisplayInfo
	displayMutex sync.RWMutex
)

func InitDisplays() []DisplayInfo {
	displayMutex.Lock()
	defer displayMutex.Unlock()

	numDisplays := robotgo.DisplaysNum()
	slog.Info("detected displays", "count", numDisplays)

	displays = make([]DisplayInfo, 0, numDisplays)
	for i := 0; i < numDisplays; i++ {
		x, y, w, h := robotgo.GetDisplayBounds(i)
		scale := robotgo.ScaleF(i)
		d := DisplayInfo{ID: i, X: x, Y: y, W: w, H: h, Scale: scale}
		displays = append(displays, d)
		slog.Debug("display info",
			"id", i, "x", x, "y", y, "w", w, "h", h, "scale", scale)
	}

	return displays
}

func GetDisplays() []DisplayInfo {
	displayMutex.RLock()
	defer displayMutex.RUnlock()
	result := make([]DisplayInfo, len(displays))
	copy(result, displays)
	return result
}

func FindDisplay(x, y int) *DisplayInfo {
	displayMutex.RLock()
	defer displayMutex.RUnlock()

	for i := range displays {
		d := &displays[i]
		if x >= d.X && x < d.X+d.W && y >= d.Y && y < d.Y+d.H {
			result := displays[i]
			return &result
		}
	}
	if len(displays) > 0 {
		result := displays[0]
		return &result
	}
	return nil
}
