package main

import (
	"fmt"
	"sync/atomic"
	"time"

	"github.com/go-vgo/robotgo"
	hook "github.com/robotn/gohook"
)

var count atomic.Int64;

func main() {
	add()
}

func takeScreenshot(x, y int){
	fmt.Println("Taking screenshot.")
	bitmap := robotgo.CaptureScreen(x - 100, y - 100, 200, 200)
	image := robotgo.ToImage(bitmap)
	filename := fmt.Sprintf("images/%d_%d.png", time.Now().UnixMilli(), count.Load())
	count.Add(1)
	robotgo.Save(image, filename)
}

func add() {
	fmt.Println("--- Please press ctrl + shift + q to stop hook ---")
	hook.Register(hook.KeyDown, []string{"q", "ctrl", "shift"}, func(e hook.Event) {
		fmt.Println("ctrl-shift-q")
		hook.End()
	})

	hook.Register(hook.MouseMove, []string{}, func(e hook.Event){
		fmt.Println("Entering hook at", e.X, e.Y);
		go takeScreenshot(int(e.X), int(e.Y))
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

