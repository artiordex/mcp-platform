// =============================================================================
// 파일명: main.go
// 경로: cmd/mcp-go-server/main.go
// 목적: Go 기반 고속 경량 MCP 서버 바이너리 엔트리포인트를 제공함
// 작성자: AI전략팀
// 작성일: 2026-09-30
// 수정일: 2026-09-30
// =============================================================================

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
		log.Printf("MCP 서버 비정상 종료됨: %v", err)
		os.Exit(1)
	}
}
