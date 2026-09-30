// =============================================================================
// 파일명: limiter.go
// 경로: internal/batchcollector/limiter.go
// 목적: 외부 공공데이터 API 대상 대량 호출 시 초당 처리율을 제어하는 토큰 버킷 레이트 리미터를 제공함
// 작성자: AI전략팀
// 작성일: 2026-09-30
// 수정일: 2026-09-30
// =============================================================================

package batchcollector

import (
	"context"
	"sync"
	"time"
)

// RateLimiter 인터페이스는 요청 허가 대기 메서드를 정의함
type RateLimiter interface {
	Wait(ctx context.Context) error
}

// TokenBucketLimiter 구조체는 토큰 버킷 알고리즘 기반 레이트 리미터임
type TokenBucketLimiter struct {
	rate       int           // 초당 생성 토큰 수임
	capacity   int           // 최대 버킷 용량임
	tokens     float64       // 현재 잔여 토큰 수임
	lastRefill time.Time     // 마지막 토큰 보충 시각임
	mu         sync.Mutex    // 동시 접근 제어 뮤텍스임
}

// NewTokenBucketLimiter 함수는 지정된 초당 처리율과 용량을 가진 리미터를 생성함
func NewTokenBucketLimiter(ratePerSec int, capacity int) *TokenBucketLimiter {
	if ratePerSec <= 0 {
		ratePerSec = 50
	}
	if capacity <= 0 {
		capacity = ratePerSec
	}
	return &TokenBucketLimiter{
		rate:       ratePerSec,
		capacity:   capacity,
		tokens:     float64(capacity),
		lastRefill: time.Now(),
	}
}

// Wait 메서드는 토큰이 1개 확보될 때까지 대기함
func (tb *TokenBucketLimiter) Wait(ctx context.Context) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		tb.mu.Lock()
		now := time.Now()
		elapsed := now.Sub(tb.lastRefill).Seconds()
		tb.lastRefill = now

		tb.tokens += elapsed * float64(tb.rate)
		if tb.tokens > float64(tb.capacity) {
			tb.tokens = float64(tb.capacity)
		}

		if tb.tokens >= 1.0 {
			tb.tokens -= 1.0
			tb.mu.Unlock()
			return nil
		}

		// 다음 토큰 1개가 찰 때까지 필요한 시간 계산
		missing := 1.0 - tb.tokens
		sleepTime := time.Duration(missing/float64(tb.rate)*float64(time.Second)) + time.Millisecond
		tb.mu.Unlock()

		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(sleepTime):
		}
	}
}
