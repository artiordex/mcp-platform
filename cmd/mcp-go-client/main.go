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
		log.Fatal(err)
	}

	fmt.Println(greeting)
}
