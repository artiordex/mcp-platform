// =============================================================================
// 파일명: server_test.go
// 경로: internal/mcpserver/server_test.go
// 목적: Go MCP 서버의 기본 도구 및 병렬 수집기 도구 등록 및 응답 무결성을 검증함
// 작성자: AI전략팀
// 작성일: 2026-09-30
// 수정일: 2026-09-30
// =============================================================================

package mcpserver

import (
	"context"
	"testing"
)

func TestGreetSuccess(t *testing.T) {
	ctx := context.Background()
	input := greetInput{Name: "홍길동"}
	_, output, err := greet(ctx, nil, input)
	if err != nil {
		t.Fatalf("greet 도구 호출 실패함: %v", err)
	}

	expected := "안녕하세요, 홍길동님! MCP Go 서버가 정상 동작 중임."
	if output.Greeting != expected {
		t.Errorf("기대값 %q, 수신값 %q", expected, output.Greeting)
	}
}

func TestGreetValidation(t *testing.T) {
	ctx := context.Background()
	input := greetInput{Name: "   "}
	_, _, err := greet(ctx, nil, input)
	if err == nil {
		t.Fatal("빈 이름 입력 시 오류가 발생해야 함")
	}
}

func TestHealthPing(t *testing.T) {
	ctx := context.Background()
	_, output, err := healthPing(ctx, nil, struct{}{})
	if err != nil {
		t.Fatalf("health_ping 실패함: %v", err)
	}

	if output.Status != "ok" {
		t.Errorf("status가 ok가 아님: %s", output.Status)
	}
	if output.NumCPU <= 0 {
		t.Errorf("NumCPU는 1 이상이어야 함: %d", output.NumCPU)
	}
}

func TestSystemMetrics(t *testing.T) {
	ctx := context.Background()
	_, output, err := systemMetrics(ctx, nil, struct{}{})
	if err != nil {
		t.Fatalf("system_metrics 실패함: %v", err)
	}

	if output.NumGoroutine <= 0 {
		t.Errorf("고루틴 수는 1 이상이어야 함: %d", output.NumGoroutine)
	}
	if output.AllocMB == "" || output.SysMB == "" {
		t.Errorf("메모리 지표 문자열이 비어 있음: alloc=%s, sys=%s", output.AllocMB, output.SysMB)
	}
}

func TestBatchCollectBids(t *testing.T) {
	ctx := context.Background()
	input := batchBidsInput{
		Keywords:    []string{"AI", "클라우드"},
		DaysBack:    7,
		Concurrency: 2,
	}

	_, output, err := batchCollectBids(ctx, nil, input)
	if err != nil {
		t.Fatalf("batch_collect_bids 호출 실패함: %v", err)
	}

	if output.TotalFetched <= 0 || output.UniqueCount <= 0 {
		t.Errorf("수집된 공고 수가 올바르지 않음: fetched=%d, unique=%d", output.TotalFetched, output.UniqueCount)
	}
	if output.TotalBudget <= 0 {
		t.Errorf("합산 예산이 0 이하임: %d", output.TotalBudget)
	}
}

func TestBatchValidateCorporate(t *testing.T) {
	ctx := context.Background()
	input := batchCorporateInput{
		BusinessNumbers: []string{"1248100998", "2208162517"},
		Concurrency:     2,
	}

	_, output, err := batchValidateCorporate(ctx, nil, input)
	if err != nil {
		t.Fatalf("batch_validate_corporate 호출 실패함: %v", err)
	}

	if output.TotalCount != 2 || output.ValidCount != 2 {
		t.Errorf("검증 결과 불일치: total=%d, valid=%d", output.TotalCount, output.ValidCount)
	}
}

func TestBenchmarkParallelCollector(t *testing.T) {
	ctx := context.Background()
	input := benchmarkCollectorInput{
		ItemCount:   10,
		Concurrency: 5,
	}

	_, output, err := benchmarkParallelCollector(ctx, nil, input)
	if err != nil {
		t.Fatalf("benchmark_parallel_collector 호출 실패함: %v", err)
	}

	if output.TotalItems != 10 {
		t.Errorf("총 항목 수 불일치: %d", output.TotalItems)
	}
	if output.SpeedupFactor <= 0.5 {
		t.Errorf("가속비가 비정상적으로 낮음: %f", output.SpeedupFactor)
	}
}
