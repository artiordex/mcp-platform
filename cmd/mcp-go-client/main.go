// =============================================================================
// 파일명: main.go
// 경로: cmd/mcp-go-client/main.go
// 목적: Go 기반 로컬 MCP 클라이언트 동작 검증 엔트리포인트를 제공함
// 작성자: AI전략팀
// 작성일: 2026-09-30
// 수정일: 2026-09-30
// =============================================================================

package main

import (
	"context"
	"fmt"
	"log"
	"time"

	"github.com/artiordex/mcp-platform/internal/mcpclient"
)

func main() {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	greeting, err := mcpclient.GreetWithLocalServer(ctx, "MCP client")
	if err != nil {
		log.Fatalf("클라이언트 실행 오류 발생함: %v", err)
	}

	fmt.Println(greeting)
}
