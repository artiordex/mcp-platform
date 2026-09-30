# MCP Platform (사내 통합 MCP 게이트웨이 및 데이터 커넥터)

사내 표준 AI 에이전트(Codex, Antigravity, Claude Desktop 등)에게 공공데이터, 조달청 나라장터, 사내 RAG-vLLM 지식 검색, 로컬 워크스페이스 도구를 단일 엔드포인트로 통합 제공하는 엔터프라이즈 MCP 플랫폼임.

---

## 1. 전체 아키텍처 (Architecture)

본 프로젝트는 `github-mcp-server`의 도구·리소스·프롬프트 분리 아키텍처 및 `awesome-mcp-clients`의 다중 클라이언트 연동 규격을 준수함.

```text
mcp-platform/
├── config/
│   ├── mcp-servers.json           # 게이트웨이 활성화 서버 목록
│   └── clients/                   # 클라이언트 연동 템플릿 (Codex, Antigravity, Claude, VS Code, Cursor)
├── src/                           # TypeScript 게이트웨이 및 클라이언트
│   ├── servers/
│   │   ├── mcp-gateway.ts         # 전체 통합 게이트웨이 (stdio)
│   │   ├── data-go-gateway.ts     # 공공데이터 및 RAG 통합 게이트웨이
│   │   ├── http-gateway.ts        # 사내 포털 연동용 HTTP/REST 게이트웨이 (:8120)
│   │   └── workspace-tools.ts     # 로컬 프로젝트 파일 탐색 (읽기 전용)
│   └── clients/
│       └── child-mcp-client.ts    # 자식 MCP 프로세스 생명주기 관리자
├── connectors/                    # Python FastMCP 데이터 커넥터
│   └── mcp_platform/
│       ├── core/
│       │   ├── common.py          # 공공데이터 공통 HTTP, 응답 파싱, 키 마스킹
│       │   └── cache.py           # In-Memory TTL 캐시 레이어 (API 쿼터 절약)
│       └── servers/
│           ├── rag.py             # 사내 RAG-vLLM 지식 검색·AI 질의·기안문 작성
│           ├── pps.py             # 조달청 나라장터 입찰공고·낙찰·계약 정보
│           ├── nts.py             # 국세청 사업자등록 진위확인 및 휴폐업 조회
│           ├── nps.py             # 국민연금 사업장 가입내역 및 고용·급여 추정
│           ├── fsc.py             # 금융위원회 기업 요약 재무제표 및 재무상태표
│           ├── portal_catalog.py  # 공공데이터포털 오픈API 및 파일 카탈로그
│           └── food_safety.py     # 식품안전나라 바코드제품·품목보고·회수식품
└── scripts/                       # 실행 및 운영 자동화 스크립트
    ├── register-clients.sh        # Codex, agy, VS Code 등 원클릭 등록 스크립트
    ├── run-mcp-gateway.sh         # mcp-platform 전체 게이트웨이 실행
    ├── run-data-go-portal.sh      # 공공데이터 게이트웨이 실행
    └── run-internal-rag.sh        # 사내 RAG-vLLM 단독 실행
```

---

## 2. 제공 도구, 리소스 및 프롬프트 (Tools, Resources, Prompts)

### 2.1 도구 (Tools)

| 구분 | 도구명 | 설명 |
| :--- | :--- | :--- |
| **사내 지식 (RAG)** | `rag_search_documents` | 사내 규정·기안문·매뉴얼 하이브리드(밀집+희소) 벡터 검색 |
| | `rag_ask_ai` | vLLM 고속 로컬 모델 기반 사내 지식 검증 질의응답 |
| | `rag_list_documents` | RAG 시스템 등록 문서 목록 페이징 조회 |
| **조달청 나라장터 (PPS)** | `search_bid_announcements` | 나라장터 입찰공고 기간별 조회 |
| | `search_successful_bids` | 낙찰 정보(물품/외자/공사/용역) 조회 |
| | `search_contracts` | 기관별 체결 계약 정보 조회 |
| | `get_bid_detail` | 입찰공고 상세 내역 단건 조회 |
| **국세청 (NTS)** | `validate_business` | 사업자등록정보(번호, 개업일, 대표자) 진위 대조 |
| | `check_business_status` | 사업자등록 상태(계속사업자, 휴업, 폐업) 일괄 조회 |
| | `batch_validate_businesses` | 복수 사업자 진위확인 일괄 처리 |
| **국민연금 (NPS)** | `search_business` | 사업장 기본정보 및 가입자 수 검색 |
| | `get_business_detail` | 가입자 수 기반 추정 월평균 급여 조회 |
| | `get_period_status` | 월별 신규 취득자 및 퇴사자 현황 조회 |
| **금융위원회 (FSC)** | `get_summary_financial_statement`| 요약 재무제표(매출액, 영업이익, 자산, 부채비율) |
| | `search_company_financial_info` | 기업 재무제표 종합 분석 텍스트 생성 |
| **카탈로그 & 식품안전** | `search_public_datasets` | 공공데이터포털 등록 데이터셋 검색 |
| | `search_food_products` | 식품안전나라 바코드연계제품 조회 |
| | `search_food_manufacturing_reports` | 품목제조보고 등록 내역 조회 |

### 2.2 리소스 (Resources)
- `internal://rag/stats`: 사내 RAG-vLLM 색인 현황 및 서비스 상태 실시간 리소스
- `catalog://data-go/types`: 공공데이터포털 지원 데이터셋 유형 명세 리소스

### 2.3 프롬프트 (Prompts)
- `draft_internal_memo`: 사내 규정을 검색하여 표준 공문서·기안서 양식으로 초안을 작성하는 프롬프트
- `analyze_bid_proposal`: 나라장터 입찰공고를 분석하고 사내 RAG 실적을 매핑하여 제안 전략을 도출하는 프롬프트

---

## 3. 빠른 시작 및 클라이언트 등록

### 3.1 환경 준비 및 빌드
```bash
cd projects/mcp-platform
npm install
npm run build
./scripts/setup-mcp-runtime.sh
```

### 3.2 Codex 및 Antigravity(agy) 원클릭 등록
아래 스크립트 실행으로 `~/.codex/config.toml`과 `~/.gemini/config/mcp_config.json`에 최신 게이트웨이가 자동 등록 및 갱신됨:
```bash
./scripts/register-clients.sh
```

### 3.3 단독 실행 테스트
- **통합 게이트웨이 실행**:
  ```bash
  ./scripts/run-mcp-gateway.sh
  ```
- **RAG 단독 실행**:
  ```bash
  ./scripts/run-internal-rag.sh
  ```
- **HTTP 게이트웨이 (:8120) 실행**:
  ```bash
  npm run start:http-gateway
  ```

---

## 4. 보안 및 인증키 관리
- 실제 API 키는 프로젝트 루트의 `.env` 파일에서 관리되며 `.gitignore`에 등록되어 있어 저장소에 커밋되지 않음.
- 모든 API 요청 및 에러 로그는 `redact_sensitive()` 함수를 거쳐 인증키가 터미널이나 클라이언트에 평문 노출되지 않도록 마스킹 처리됨.
- 공공데이터포털 API 호출 시 `api_cache`(TTL In-Memory 캐시)가 적용되어 불필요한 일일 호출 쿼터 소모를 방지함.
