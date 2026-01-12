package server

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"time"
)

type Server struct {
	httpServer *http.Server
	mux        *http.ServeMux
}

func New(port int) *Server {
	mux := http.NewServeMux()

	return &Server{
		mux: mux,
		httpServer: &http.Server{
			Addr:         fmt.Sprintf(":%d", port),
			Handler:      LoggingMiddleware(mux),
			ReadTimeout:  5 * time.Second,
			WriteTimeout: 10 * time.Second,
		},
	}
}

func (s *Server) RegisterHandler(pattern string, handler http.HandlerFunc) {
	s.mux.HandleFunc(pattern, handler)
}

func (s *Server) Start() error {
	slog.Info("starting HTTP server", "addr", s.httpServer.Addr)
	return s.httpServer.ListenAndServe()
}

func (s *Server) Shutdown(ctx context.Context) error {
	slog.Info("shutting down HTTP server")
	return s.httpServer.Shutdown(ctx)
}
