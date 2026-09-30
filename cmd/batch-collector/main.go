// =============================================================================
// 파일명: main.go
// 경로: cmd/batch-collector/main.go
// 목적: Go 고성능 병렬 공공데이터 수집기 및 벤치마크 CLI 엔트리포인트를 제공함
// 작성자: AI전략팀
// 작성일: 2026-09-30
// 수정일: 2026-09-30
// =============================================================================

package main

import (
	"context"
	"flag"
	"fmt"
	"strings"
	"time"

	"github.com/artiordex/mcp-platform/internal/batchcollector"
)

func main() {
	mode := flag.String("mode", "benchmark", "실행 모드 (benchmark, bids, corporate, all)임")
	workers := flag.Int("workers", 10, "동시 고루틴 워커 수임")
	items := flag.Int("items", 30, "벤치마크 항목 수임")
	terms := flag.String("keywords", "인공지능,빅데이터,클라우드,정보보안", "수집 키워드(쉼표 구분)임")
	flag.Parse()

	ctx := context.Background()

	if *mode == "benchmark" || *mode == "all" {
		bench := batchcollector.RunBenchmark(ctx, *items, *workers, 5*time.Millisecond)
		fmt.Printf("  - 고루틴 워커 풀 벤치마크 (항목 수: %d개, 워커 수: %d개)\n", bench.TotalItems, bench.GoroutineCount)
		fmt.Printf("  - 순차 실행: %d ms | 고루틴 병렬 실행: %d ms (가속비: %.2fx)\n", bench.SequentialMS, bench.ParallelMS, bench.SpeedupFactor)
	}

	if *mode == "bids" || *mode == "all" {
		kwList := strings.Split(*terms, ",")
		bids := batchcollector.CollectBidsParallel(ctx, kwList, 7, *workers)
		fmt.Printf("  - 나라장터 다중 키워드 병렬 수집: %d건 수집 완료 (고유: %d건, 예산합계: %d억원, 소요시간: %d ms)\n",
			bids.TotalFetched, bids.UniqueCount, bids.TotalBudget/100_000_000, bids.ElapsedMS)
	}

	if *mode == "corporate" || *mode == "all" {
		bnos := []string{"1248100998", "2208162517", "1018111222", "1058134746", "1108147490"}
		corp := batchcollector.ValidateCorporateParallel(ctx, bnos, *workers)
		fmt.Printf("  - 기업 사업자등록번호 병렬 검증: %d건 완료 (유효: %d건, 처리속도: %.1f req/sec)\n",
			corp.TotalCount, corp.ValidCount, corp.ThroughputRPS)
	}
}
