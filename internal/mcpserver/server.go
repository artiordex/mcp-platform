// =============================================================================
// 파일명: server.go
// 경로: internal/mcpserver/server.go
// 목적: 고루틴 병렬 수집기 및 고성능 Go stdio MCP 서버를 제공함
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

	"github.com/artiordex/mcp-platform/internal/batchcollector"
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

type metricsOutput struct {
	NumGoroutine int    `json:"num_goroutine" jsonschema:"실행 중인 고루틴 수임"`
	AllocMB      string `json:"alloc_mb" jsonschema:"할당된 힙 메모리 용량임"`
	SysMB        string `json:"sys_mb" jsonschema:"운영체제로부터 할당받은 시스템 메모리 용량임"`
	NumGC        uint32 `json:"num_gc" jsonschema:"수행된 가비지 컬렉션 주기 횟수임"`
}

type batchBidsInput struct {
	Keywords    []string `json:"keywords" jsonschema:"수집할 키워드 목록(예: AI, 클라우드, 데이터)임"`
	DaysBack    int      `json:"days_back,omitempty" jsonschema:"과거 며칠간의 공고를 수집할지 일수(기본값 7)임"`
	Concurrency int      `json:"concurrency,omitempty" jsonschema:"동시 고루틴 워커 수(기본값 5)임"`
}

type batchCorporateInput struct {
	BusinessNumbers []string `json:"business_numbers" jsonschema:"검증할 사업자등록번호 목록(10자리)임"`
	Concurrency     int      `json:"concurrency,omitempty" jsonschema:"동시 고루틴 워커 수(기본값 8)임"`
}

type benchmarkCollectorInput struct {
	ItemCount   int `json:"item_count,omitempty" jsonschema:"벤치마크 테스트 항목 수(기본값 20)임"`
	Concurrency int `json:"concurrency,omitempty" jsonschema:"동시 고루틴 워커 수(기본값 10)임"`
}

// New 함수는 Go MCP 서버 인스턴스를 생성하고 등록 가능한 도구를 바인딩함
func New() *mcp.Server {
	server := mcp.NewServer(&mcp.Implementation{
		Name:    "mcp-platform-go-server",
		Version: "0.1.0",
	}, &mcp.ServerOptions{
		Instructions: "mcp-platform 고성능 병렬 수집기 및 초경량 Go stdio MCP 서버임",
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

	mcp.AddTool(server, &mcp.Tool{
		Name:        "system_metrics",
		Description: "실행 중인 고루틴 수 및 메모리(RAM) 할당 지표를 반환함",
	}, systemMetrics)

	mcp.AddTool(server, &mcp.Tool{
		Name:        "batch_collect_bids",
		Description: "복수 키워드 및 기간에 대해 나라장터 입찰공고를 고루틴 워커 풀로 병렬 수집함",
	}, batchCollectBids)

	mcp.AddTool(server, &mcp.Tool{
		Name:        "batch_validate_corporate",
		Description: "다수 기업의 사업자등록번호 진위를 고루틴 병렬로 초고속 검증함",
	}, batchValidateCorporate)

	mcp.AddTool(server, &mcp.Tool{
		Name:        "benchmark_parallel_collector",
		Description: "순차 처리 대비 고루틴 병렬 처리의 가속비 및 성능 지표를 측정함",
	}, benchmarkParallelCollector)

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

func systemMetrics(_ context.Context, _ *mcp.CallToolRequest, _ struct{}) (*mcp.CallToolResult, metricsOutput, error) {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)

	return nil, metricsOutput{
		NumGoroutine: runtime.NumGoroutine(),
		AllocMB:      fmt.Sprintf("%.2f MB", float64(m.Alloc)/(1024*1024)),
		SysMB:        fmt.Sprintf("%.2f MB", float64(m.Sys)/(1024*1024)),
		NumGC:        m.NumGC,
	}, nil
}

func batchCollectBids(ctx context.Context, _ *mcp.CallToolRequest, input batchBidsInput) (*mcp.CallToolResult, batchcollector.BatchBidsResult, error) {
	result := batchcollector.CollectBidsParallel(ctx, input.Keywords, input.DaysBack, input.Concurrency)
	return nil, result, nil
}

func batchValidateCorporate(ctx context.Context, _ *mcp.CallToolRequest, input batchCorporateInput) (*mcp.CallToolResult, batchcollector.BatchCorporateResult, error) {
	result := batchcollector.ValidateCorporateParallel(ctx, input.BusinessNumbers, input.Concurrency)
	return nil, result, nil
}

func benchmarkParallelCollector(ctx context.Context, _ *mcp.CallToolRequest, input benchmarkCollectorInput) (*mcp.CallToolResult, batchcollector.BenchmarkComparison, error) {
	count := input.ItemCount
	if count <= 0 {
		count = 20
	}
	concurrency := input.Concurrency
	if concurrency <= 0 {
		concurrency = 10
	}

	result := batchcollector.RunBenchmark(ctx, count, concurrency, 5*time.Millisecond)
	return nil, result, nil
}
