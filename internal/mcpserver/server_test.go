// =============================================================================
// 파일명: server_test.go
// 경로: internal/mcpserver/server_test.go
// 목적: Go MCP 서버의 도구 등록 및 응답 무결성을 검증함
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
