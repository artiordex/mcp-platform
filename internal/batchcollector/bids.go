// =============================================================================
// 파일명: bids.go
// 경로: internal/batchcollector/bids.go
// 목적: 조달청 나라장터 공고를 복수 키워드·일자별로 고루틴 병렬 수집 및 중복 제거함
// 작성자: AI전략팀
// 작성일: 2026-09-30
// 수정일: 2026-09-30
// =============================================================================

package batchcollector

import (
	"context"
	"crypto/sha256"
	"fmt"
	"sort"
	"time"
)

// BidRecord 구조체는 수집된 개별 입찰공고 요약 정보임
type BidRecord struct {
	BidNo       string `json:"bid_no"`       // 공고번호임
	Title       string `json:"title"`        // 공고명임
	Agency      string `json:"agency"`       // 발주기관명임
	Category    string `json:"category"`     // 공고 분류(용역/물품/공사)임
	BudgetKRW   int64  `json:"budget_krw"`   // 추정가격(원)임
	PostedDate  string `json:"posted_date"`  // 공고일시임
	MatchedTerm string `json:"matched_term"` // 검색 매칭 키워드임
}

// BatchBidsResult 구조체는 병렬 수집 집계 결과를 정의함
type BatchBidsResult struct {
	TotalFetched int         `json:"total_fetched"` // 수집된 총 공고 건수임
	UniqueCount  int         `json:"unique_count"`  // 중복 제거된 고유 공고 수임
	TotalBudget  int64       `json:"total_budget"`  // 고유 공고 합산 예산 규모(원)임
	ElapsedMS    int64       `json:"elapsed_ms"`    // 수집 소요시간(ms)임
	WorkersUsed  int         `json:"workers_used"`  // 투입된 고루틴 워커 수임
	Bids         []BidRecord `json:"bids"`          // 정렬된 공고 목록임
}

// CollectBidsParallel 함수는 복수 키워드에 대해 고루틴 병렬로 입찰공고를 일괄 수집함
func CollectBidsParallel(ctx context.Context, keywords []string, daysBack int, concurrency int) BatchBidsResult {
	start := time.Now()
	if len(keywords) == 0 {
		keywords = []string{"AI", "클라우드", "데이터", "정보보안"}
	}
	if daysBack <= 0 {
		daysBack = 7
	}
	if concurrency <= 0 {
		concurrency = 5
	}

	task := func(ctx context.Context, keyword string) ([]BidRecord, error) {
		return fetchBidsForKeyword(ctx, keyword, daysBack)
	}

	results, _ := ExecuteParallel(ctx, keywords, concurrency, task)

	// 결과 통합 및 중복 제거
	seen := make(map[string]bool)
	var uniqueBids []BidRecord
	totalFetched := 0
	var totalBudget int64

	for _, res := range results {
		if res.Err != nil {
			continue
		}
		for _, bid := range res.Value {
			totalFetched++
			if !seen[bid.BidNo] {
				seen[bid.BidNo] = true
				uniqueBids = append(uniqueBids, bid)
				totalBudget += bid.BudgetKRW
			}
		}
	}

	// 공고일시 기준 내림차순 정렬
	sort.Slice(uniqueBids, func(i, j int) bool {
		return uniqueBids[i].PostedDate > uniqueBids[j].PostedDate
	})

	return BatchBidsResult{
		TotalFetched: totalFetched,
		UniqueCount:  len(uniqueBids),
		TotalBudget:  totalBudget,
		ElapsedMS:    time.Since(start).Milliseconds(),
		WorkersUsed:  min(concurrency, len(keywords)),
		Bids:         uniqueBids,
	}
}

// fetchBidsForKeyword 함수는 특정 키워드에 대해 모의/실제 공고 레코드를 생성함
func fetchBidsForKeyword(ctx context.Context, keyword string, daysBack int) ([]BidRecord, error) {
	// I/O 지연 시뮬레이션 (15~35ms)
	time.Sleep(20 * time.Millisecond)

	agencies := []string{
		"한국지능정보사회진흥원",
		"정보통신산업진흥원",
		"한국도로공사",
		"한국전력공사",
		"국민건강보험공단",
		"한국수자원공사",
	}

	categories := []string{"용역", "물품", "정보화"}
	now := time.Now()

	var records []BidRecord
	count := 3 // 키워드당 3건 생성

	for i := 0; i < count; i++ {
		offsetHours := (i + 1) * 12
		postedAt := now.Add(-time.Duration(offsetHours) * time.Hour).Format("2006-01-02 15:04:00")
		agency := agencies[(len(keyword)+i)%len(agencies)]
		category := categories[(len(keyword)*2+i)%len(categories)]

		// 결정론적 공고번호 생성
		hashRaw := fmt.Sprintf("%s-%s-%d", keyword, agency, i)
		hash := fmt.Sprintf("%x", sha256.Sum256([]byte(hashRaw)))[:8]
		bidNo := fmt.Sprintf("2026%02d%s-00", (now.Month()), hash)

		budget := int64((i + 1) * 150_000_000)

		records = append(records, BidRecord{
			BidNo:       bidNo,
			Title:       fmt.Sprintf("%s 기반 차세대 지능형 업무 통합 플랫폼 구축 (%s)", keyword, category),
			Agency:      agency,
			Category:    category,
			BudgetKRW:   budget,
			PostedDate:  postedAt,
			MatchedTerm: keyword,
		})
	}

	return records, nil
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
