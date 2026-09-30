// =============================================================================
// 파일명: client.go
// 경로: internal/mcpclient/client.go
// 목적: 로컬 stdio 기반 Go MCP 서버와 세션을 맺고 도구를 호출하는 클라이언트를 제공함
// 작성자: AI전략팀
// 작성일: 2026-09-30
// 수정일: 2026-09-30
// =============================================================================

package mcpclient

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strings"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// GreetWithLocalServer 함수는 로컬 stdio Go MCP 서버를 기동하고 greet 도구를 호출함
func GreetWithLocalServer(ctx context.Context, name string) (string, error) {
	client := mcp.NewClient(&mcp.Implementation{
		Name:    "mcp-platform-go-client",
		Version: "0.1.0",
	}, nil)

	command := exec.CommandContext(ctx, "go", "run", "./cmd/mcp-go-server")
	command.Stderr = os.Stderr
	session, err := client.Connect(ctx, &mcp.CommandTransport{Command: command}, nil)
	if err != nil {
		return "", fmt.Errorf("로컬 MCP 서버 연결 실패함: %w", err)
	}
	defer session.Close()

	result, err := session.CallTool(ctx, &mcp.CallToolParams{
		Name:      "greet",
		Arguments: map[string]any{"name": name},
	})
	if err != nil {
		return "", fmt.Errorf("greet 도구 호출 실패함: %w", err)
	}
	if result.IsError {
		messages := make([]string, 0, len(result.Content))
		for _, content := range result.Content {
			if text, ok := content.(*mcp.TextContent); ok {
				messages = append(messages, text.Text)
			}
		}
		return "", fmt.Errorf("greet 도구 오류 반환함: %s", strings.Join(messages, "; "))
	}

	var output struct {
		Greeting string `json:"greeting"`
	}
	payload, err := json.Marshal(result.StructuredContent)
	if err != nil {
		return "", fmt.Errorf("응답 직렬화 실패함: %w", err)
	}
	if err := json.Unmarshal(payload, &output); err != nil {
		return "", fmt.Errorf("응답 역직렬화 실패함: %w", err)
	}
	if output.Greeting == "" {
		return "", fmt.Errorf("greet 도구 결과 메시지가 비어 있음")
	}

	return output.Greeting, nil
}
