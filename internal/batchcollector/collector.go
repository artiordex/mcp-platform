// =============================================================================
// 파일명: collector.go
// 경로: internal/batchcollector/collector.go
// 목적: 고루틴 기반 고성능 병렬 수집기 및 워커 풀(Worker Pool)을 제공함
// 작성자: AI전략팀
// 작성일: 2026-09-30
// 수정일: 2026-09-30
// =============================================================================

package batchcollector

import (
	"context"
	"net/http"
	"sync"
	"time"
)

// Config 구조체는 병렬 수집기의 튜닝 옵션을 정의함
type Config struct {
	Concurrency int           // 동시 워커 고루틴 수임
	Timeout     time.Duration // 요청 제한 시간임
	RateLimit   int           // 초당 최대 요청 허용 수임
}

// DefaultConfig 함수는 기본 권장 설정을 반환함
func DefaultConfig() Config {
	return Config{
		Concurrency: 10,
		Timeout:     10 * time.Second,
		RateLimit:   50,
	}
}

// Collector 구조체는 고성능 HTTP 클라이언트와 워커 풀을 관리함
type Collector struct {
	client    *http.Client
	config    Config
	rateLimit chan struct{}
}

// NewCollector 함수는 새로운 병렬 수집기 인스턴스를 생성함
func NewCollector(cfg Config) *Collector {
	if cfg.Concurrency <= 0 {
		cfg.Concurrency = 10
	}
	if cfg.Timeout <= 0 {
		cfg.Timeout = 10 * time.Second
	}

	transport := &http.Transport{
		MaxIdleConns:        100,
		MaxIdleConnsPerHost: 20,
		IdleConnTimeout:     90 * time.Second,
		DisableCompression: false,
	}

	c := &Collector{
		client: &http.Client{
			Transport: transport,
			Timeout:   cfg.Timeout,
		},
		config: cfg,
	}

	if cfg.RateLimit > 0 {
		c.rateLimit = make(chan struct{}, cfg.RateLimit)
	}

	return c
}

// Task 함수 시그니처는 개별 워커가 수행할 작업임
type Task[T any, R any] func(ctx context.Context, item T) (R, error)

// Result 구조체는 태스크 수행 결과 및 오류를 보관함
type Result[R any] struct {
	Value R
	Err   error
}

// ExecuteParallel 함수는 입력 슬라이스의 항목들을 지정된 동시성으로 병렬 처리함
func ExecuteParallel[T any, R any](
	ctx context.Context,
	items []T,
	concurrency int,
	task Task[T, R],
) ([]Result[R], time.Duration) {
	start := time.Now()
	if len(items) == 0 {
		return nil, 0
	}

	if concurrency <= 0 {
		concurrency = 10
	}
	if concurrency > len(items) {
		concurrency = len(items)
	}

	type indexedTask struct {
		index int
		item  T
	}

	type indexedResult struct {
		index  int
		result Result[R]
	}

	taskChan := make(chan indexedTask, len(items))
	resultChan := make(chan indexedResult, len(items))

	var wg sync.WaitGroup

	// 워커 고루틴 풀 기동
	for w := 0; w < concurrency; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for t := range taskChan {
				select {
				case <-ctx.Done():
					resultChan <- indexedResult{
						index:  t.index,
						result: Result[R]{Err: ctx.Err()},
					}
				default:
					val, err := task(ctx, t.item)
					resultChan <- indexedResult{
						index:  t.index,
						result: Result[R]{Value: val, Err: err},
					}
				}
			}
		}()
	}

	// 작업 큐 적재
	for i, item := range items {
		taskChan <- indexedTask{index: i, item: item}
	}
	close(taskChan)

	// 워커 종료 대기 및 결과 채널 닫기
	go func() {
		wg.Wait()
		close(resultChan)
	}()

	// 인덱스 순서대로 결과 복원
	results := make([]Result[R], len(items))
	for r := range resultChan {
		results[r.index] = r.result
	}

	elapsed := time.Since(start)
	return results, elapsed
}

// BenchmarkComparison 구조체는 순차 대비 병렬 벤치마크 지표를 정의함
type BenchmarkComparison struct {
	TotalItems     int     `json:"total_items"`
	SequentialMS   int64   `json:"sequential_ms"`
	ParallelMS     int64   `json:"parallel_ms"`
	SpeedupFactor  float64 `json:"speedup_factor"`
	GoroutineCount int     `json:"goroutine_count"`
}

// RunBenchmark 함수는 CPU/IO 작업 시뮬레이션으로 병렬 처리 가속비를 측정함
func RunBenchmark(ctx context.Context, count int, concurrency int, workDuration time.Duration) BenchmarkComparison {
	if count <= 0 {
		count = 20
	}
	if concurrency <= 0 {
		concurrency = 10
	}

	items := make([]int, count)
	for i := 0; i < count; i++ {
		items[i] = i + 1
	}

	dummyTask := func(ctx context.Context, item int) (int, error) {
		time.Sleep(workDuration)
		return item * 2, nil
	}

	// 1. 순차 실행 측정
	seqStart := time.Now()
	for _, item := range items {
		select {
		case <-ctx.Done():
			break
		default:
			_, _ = dummyTask(ctx, item)
		}
	}
	seqElapsed := time.Since(seqStart)

	// 2. 병렬 고루틴 실행 측정
	_, parElapsed := ExecuteParallel(ctx, items, concurrency, dummyTask)

	speedup := float64(seqElapsed.Microseconds()) / float64(max(parElapsed.Microseconds(), 1))

	return BenchmarkComparison{
		TotalItems:     count,
		SequentialMS:   seqElapsed.Milliseconds(),
		ParallelMS:     parElapsed.Milliseconds(),
		SpeedupFactor:  float64(int(speedup*100)) / 100, // 소수점 둘째자리 절삭
		GoroutineCount: concurrency,
	}
}

func max(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}
