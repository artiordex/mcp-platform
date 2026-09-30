package mcpserver

import (
	"context"
	"fmt"
	"strings"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type greetInput struct {
	Name string `json:"name" jsonschema:"the name of the person to greet"`
}

type greetOutput struct {
	Greeting string `json:"greeting" jsonschema:"a friendly greeting"`
}

// New creates the Go MCP server and registers its starter tool.
func New() *mcp.Server {
	server := mcp.NewServer(&mcp.Implementation{
		Name:    "mcp-platform-go-server",
		Version: "0.1.0",
	}, &mcp.ServerOptions{
		Instructions: "A starter MCP server for the mcp-platform project.",
		Capabilities: &mcp.ServerCapabilities{
			Tools: &mcp.ToolCapabilities{},
		},
	})

	mcp.AddTool(server, &mcp.Tool{
		Name:        "greet",
		Description: "Return a greeting for a name.",
	}, greet)

	return server
}

// Run serves MCP messages over stdio until the client disconnects.
func Run(ctx context.Context) error {
	return New().Run(ctx, &mcp.StdioTransport{})
}

func greet(_ context.Context, _ *mcp.CallToolRequest, input greetInput) (*mcp.CallToolResult, greetOutput, error) {
	name := strings.TrimSpace(input.Name)
	if name == "" {
		return nil, greetOutput{}, fmt.Errorf("name is required")
	}

	return nil, greetOutput{Greeting: fmt.Sprintf("Hello, %s!", name)}, nil
}
