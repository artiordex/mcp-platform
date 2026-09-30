// =============================================================================
// 파일명: collector_test.go
// 경로: internal/batchcollector/collector_test.go
// 목적: 병렬 수집기 워커 풀, 입찰공고 병렬 수집, 기업 검증 병렬 처리의 무결성을 검증함
// 작성자: AI전략팀
// 작성일: 2026-09-30
// 수정일: 2026-09-30
// =============================================================================

package batchcollector

import (
	"context"
	"testing"
	"time"
)

func TestExecuteParallel(t *testing.T) {
	ctx := context.Background()
	items := []int{1, 2, 3, 4, 5}

	task := func(ctx context.Context, item int) (int, error) {
		return item * 10, nil
	}

	results, elapsed := ExecuteParallel(ctx, items, 3, task)
	if len(results) != 5 {
		t.Fatalf("결과 항목 수가 5가 아님: %d", len(results))
	}
	if elapsed < 0 {
		t.Fatal("소요시간이 음수일 수 없음")
	}

	for i, r := range results {
		if r.Err != nil {
			t.Errorf("항목 %d에서 에러 발생: %v", i, r.Err)
		}
		expected := (i + 1) * 10
		if r.Value != expected {
			t.Errorf("인덱스 %d 기대값 %d, 실제값 %d", i, expected, r.Value)
		}
	}
}

func TestCollectBidsParallel(t *testing.T) {
	ctx := context.Background()
	keywords := []string{"AI", "클라우드", "데이터"}

	res := CollectBidsParallel(ctx, keywords, 7, 3)

	if res.TotalFetched <= 0 {
		t.Errorf("수집된 공고 수가 0 이하임: %d", res.TotalFetched)
	}
	if res.UniqueCount <= 0 {
		t.Errorf("고유 공고 수가 0 이하임: %d", res.UniqueCount)
	}
	if res.TotalBudget <= 0 {
		t.Errorf("합산 예산이 0 이하임: %d", res.TotalBudget)
	}
	if len(res.Bids) != res.UniqueCount {
		t.Errorf("반환된 공고 슬라이스 길이가 UniqueCount와 불일치함: %d vs %d", len(res.Bids), res.UniqueCount)
	}
}

func TestValidateCorporateParallel(t *testing.T) {
	ctx := context.Background()
	bnos := []string{
		"1248100998", // 삼성전자 (유효)
		"2208162517", // LG전자 (유효)
		"0000000000", // 비유효
	}

	res := ValidateCorporateParallel(ctx, bnos, 2)

	if res.TotalCount != 3 {
		t.Errorf("총 건수 불일치: %d", res.TotalCount)
	}
	if res.ValidCount != 2 {
		t.Errorf("유효 건수 불일치 (기대 2, 실제 %d)", res.ValidCount)
	}
	if res.ThroughputRPS <= 0 {
		t.Errorf("RPS가 0 이하임: %f", res.ThroughputRPS)
	}
}

func TestRunBenchmark(t *testing.T) {
	ctx := context.Background()
	bench := RunBenchmark(ctx, 10, 5, 5*time.Millisecond)

	if bench.TotalItems != 10 {
		t.Errorf("총 항목 수 불일치: %d", bench.TotalItems)
	}
	if bench.GoroutineCount != 5 {
		t.Errorf("고루틴 수 불일치: %d", bench.GoroutineCount)
	}
	if bench.SpeedupFactor <= 0.5 {
		t.Errorf("가속비가 비정상적으로 낮음: %f", bench.SpeedupFactor)
	}
}
