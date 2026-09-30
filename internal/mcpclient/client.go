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

// GreetWithLocalServer demonstrates a Go SDK client connecting to the local
// Go server over stdio and calling its greet tool.
func GreetWithLocalServer(ctx context.Context, name string) (string, error) {
	client := mcp.NewClient(&mcp.Implementation{
		Name:    "mcp-platform-go-client",
		Version: "0.1.0",
	}, nil)

	command := exec.CommandContext(ctx, "go", "run", "./cmd/mcp-go-server")
	command.Stderr = os.Stderr
	session, err := client.Connect(ctx, &mcp.CommandTransport{Command: command}, nil)
	if err != nil {
		return "", fmt.Errorf("connect to local MCP server: %w", err)
	}
	defer session.Close()

	result, err := session.CallTool(ctx, &mcp.CallToolParams{
		Name:      "greet",
		Arguments: map[string]any{"name": name},
	})
	if err != nil {
		return "", fmt.Errorf("call greet tool: %w", err)
	}
	if result.IsError {
		messages := make([]string, 0, len(result.Content))
		for _, content := range result.Content {
			if text, ok := content.(*mcp.TextContent); ok {
				messages = append(messages, text.Text)
			}
		}
		return "", fmt.Errorf("greet tool returned an error: %s", strings.Join(messages, "; "))
	}

	var output struct {
		Greeting string `json:"greeting"`
	}
	payload, err := json.Marshal(result.StructuredContent)
	if err != nil {
		return "", fmt.Errorf("encode greet result: %w", err)
	}
	if err := json.Unmarshal(payload, &output); err != nil {
		return "", fmt.Errorf("decode greet result: %w", err)
	}
	if output.Greeting == "" {
		return "", fmt.Errorf("greet tool returned no greeting")
	}

	return output.Greeting, nil
}
