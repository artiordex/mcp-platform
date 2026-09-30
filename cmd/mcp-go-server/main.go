package main

import (
	"context"
	"errors"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/artiordex/mcp-platform/internal/mcpserver"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if err := mcpserver.Run(ctx); err != nil && !errors.Is(err, context.Canceled) {
		log.Printf("MCP server stopped: %v", err)
		os.Exit(1)
	}
}
