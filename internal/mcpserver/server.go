// =============================================================================
// 파일명: server.go
// 경로: internal/mcpserver/server.go
// 목적: 고성능 경량 Go 기반 stdio MCP 서버 및 기본 도구를 제공함
// 작성자: AI전략팀
// 작성일: 2026-09-30
// 수정일: 2026-09-30
// =============================================================================

package mcpserver

import (
	"context"
	"fmt"
	"runtime"
	"strings"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type greetInput struct {
	Name string `json:"name" jsonschema:"인사 대상자 이름임"`
}

type greetOutput struct {
	Greeting string `json:"greeting" jsonschema:"생성된 환영 메시지임"`
}

type pingOutput struct {
	Status    string `json:"status" jsonschema:"서버 상태임"`
	Timestamp string `json:"timestamp" jsonschema:"응답 시각임"`
	GoVersion string `json:"go_version" jsonschema:"Go 런타임 버전임"`
	NumCPU    int    `json:"num_cpu" jsonschema:"가용 CPU 코어 수임"`
}

// New 함수는 Go MCP 서버 인스턴스를 생성하고 등록 가능한 도구를 바인딩함
func New() *mcp.Server {
	server := mcp.NewServer(&mcp.Implementation{
		Name:    "mcp-platform-go-server",
		Version: "0.1.0",
	}, &mcp.ServerOptions{
		Instructions: "mcp-platform 초경량 Go stdio MCP 서버임",
		Capabilities: &mcp.ServerCapabilities{
			Tools: &mcp.ToolCapabilities{},
		},
	})

	mcp.AddTool(server, &mcp.Tool{
		Name:        "greet",
		Description: "이름을 전달받아 환영 메시지를 반환함",
	}, greet)

	mcp.AddTool(server, &mcp.Tool{
		Name:        "health_ping",
		Description: "Go 런타임 상태 및 하드웨어 가용 지표를 즉각 응답함",
	}, healthPing)

	return server
}

// Run 함수는 클라이언트 연결 종료 시까지 stdio 스트림으로 MCP 메시지를 중계함
func Run(ctx context.Context) error {
	return New().Run(ctx, &mcp.StdioTransport{})
}

func greet(_ context.Context, _ *mcp.CallToolRequest, input greetInput) (*mcp.CallToolResult, greetOutput, error) {
	name := strings.TrimSpace(input.Name)
	if name == "" {
		return nil, greetOutput{}, fmt.Errorf("name 매개변수가 필수임")
	}

	return nil, greetOutput{Greeting: fmt.Sprintf("안녕하세요, %s님! MCP Go 서버가 정상 동작 중임.", name)}, nil
}

func healthPing(_ context.Context, _ *mcp.CallToolRequest, _ struct{}) (*mcp.CallToolResult, pingOutput, error) {
	return nil, pingOutput{
		Status:    "ok",
		Timestamp: time.Now().Format(time.RFC3339),
		GoVersion: runtime.Version(),
		NumCPU:    runtime.NumCPU(),
	}, nil
}
