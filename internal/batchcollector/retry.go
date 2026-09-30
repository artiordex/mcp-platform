// =============================================================================
// 파일명: retry.go
// 경로: internal/batchcollector/retry.go
// 목적: 네트워크 장애 및 일시적 서버 오류에 대응하는 지수 백오프 재시도 메커니즘을 제공함
// 작성자: AI전략팀
// 작성일: 2026-09-30
// 수정일: 2026-09-30
// =============================================================================

package batchcollector

import (
	"context"
	"fmt"
	"time"
)

// RetryConfig 구조체는 지수 백오프 재시도 옵션을 정의함
type RetryConfig struct {
	MaxRetries     int           // 최대 재시도 횟수임
	InitialBackoff time.Duration // 초기 대기 시간임
	MaxBackoff     time.Duration // 최대 대기 시간임
	Multiplier     float64       // 대기 시간 증가 배수임
}

// DefaultRetryConfig 함수는 기본 권장 재시도 설정을 반환함
func DefaultRetryConfig() RetryConfig {
	return RetryConfig{
		MaxRetries:     3,
		InitialBackoff: 100 * time.Millisecond,
		MaxBackoff:     2 * time.Second,
		Multiplier:     2.0,
	}
}

// WithRetry 함수는 주어진 태스크 함수를 지수 백오프로 재시도 래핑함
func WithRetry[T any, R any](cfg RetryConfig, task Task[T, R]) Task[T, R] {
	if cfg.MaxRetries <= 0 {
		return task
	}
	if cfg.InitialBackoff <= 0 {
		cfg.InitialBackoff = 100 * time.Millisecond
	}
	if cfg.Multiplier <= 1.0 {
		cfg.Multiplier = 2.0
	}

	return func(ctx context.Context, item T) (R, error) {
		var lastErr error
		backoff := cfg.InitialBackoff

		for attempt := 0; attempt <= cfg.MaxRetries; attempt++ {
			if attempt > 0 {
				select {
				case <-ctx.Done():
					var zero R
					return zero, ctx.Err()
				case <-time.After(backoff):
				}
				backoff = time.Duration(float64(backoff) * cfg.Multiplier)
				if cfg.MaxBackoff > 0 && backoff > cfg.MaxBackoff {
					backoff = cfg.MaxBackoff
				}
			}

			val, err := task(ctx, item)
			if err == nil {
				return val, nil
			}
			lastErr = err
		}

		var zero R
		return zero, fmt.Errorf("최대 재시도(%d회) 초과 실패: %w", cfg.MaxRetries, lastErr)
	}
}
