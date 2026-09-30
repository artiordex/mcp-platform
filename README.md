# MCP Platform (사내 통합 MCP 게이트웨이 및 데이터 커넥터)

사내 표준 AI 에이전트(Codex, Antigravity, Claude Desktop, VS Code, Cursor 등)에게 공공데이터, 조달청 나라장터, DART 전자공시, 도로명주소, 사내 RAG-vLLM 지식 검색, 로컬 워크스페이스 도구를 단일 엔드포인트로 통합 제공하는 엔터프라이즈 MCP 플랫폼임.

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
│   │   ├── http-gateway.ts        # 사내 포털 연동용 HTTP/REST 게이트웨이 (:8120, OpenAPI 3.0, SSE)
│   │   └── workspace-tools.ts     # 로컬 프로젝트 파일 탐색 및 코드 분석 (읽기 전용 샌드박스)
│   └── clients/
│       └── child-mcp-client.ts    # 자식 MCP 프로세스 생명주기 관리자
├── connectors/                    # Python FastMCP 데이터 커넥터
│   └── mcp_platform/
│       ├── core/
│       │   ├── common.py          # 공공데이터 공통 HTTP, 응답 파싱, 키 마스킹
│       │   └── cache.py           # In-Memory TTL 캐시 레이어 (API 쿼터 절약)
│       └── servers/
│           ├── corporate_intelligence.py # 기업 종합 분석 (세무+고용+재무+사내실적+DART 융합)
│           ├── dart.py            # 금융감독원 OpenDART 전자공시 보고서 및 기업 개요
│           ├── address.py         # 행정안전부 도로명주소 및 행정구역 표준코드
│           ├── rag.py             # 사내 RAG-vLLM 지식 검색·AI 질의·문서 인제스트
│           ├── pps.py             # 조달청 나라장터 입찰공고·발주계획·낙찰·계약 정보
│           ├── nts.py             # 국세청 사업자등록 진위확인 및 휴폐업 조회
│           ├── nps.py             # 국민연금 사업장 가입내역 및 고용·급여 추정
│           ├── fsc.py             # 금융위원회 기업 요약 재무제표 및 재무상태표
│           ├── portal_catalog.py  # 공공데이터포털 오픈API 및 파일 카탈로그
│           └── food_safety.py     # 식품안전나라 바코드제품·품목보고·회수식품
├── cmd/ & internal/               # Go 기반 초경량 고속 MCP stdio 서버/클라이언트
└── scripts/                       # 실행 및 운영 자동화 스크립트
    ├── doctor.sh                  # 시스템 상태, 의존성, 포트 종합 진단 스크립트
    ├── benchmark-e2e.sh           # 실무 시나리오 E2E 및 캐시 레이턴시 벤치마크
    ├── register-clients.sh        # Codex, agy, VS Code 등 원클릭 등록 스크립트
    ├── run-mcp-gateway.sh         # mcp-platform 전체 게이트웨이 실행
    ├── run-data-go-portal.sh      # 공공데이터 게이트웨이 실행
    ├── run-internal-rag.sh        # 사내 RAG-vLLM 단독 실행
    ├── run-corporate-intelligence.sh # 기업 종합 분석 서버 단독 실행
    ├── run-dart-filings.sh        # DART 전자공시 서버 단독 실행
    ├── run-address-lookup.sh      # 도로명주소 서버 단독 실행
    └── run-mcp-go-server.sh       # Go MCP 초경량 서버 실행
```

---

## 2. 제공 도구, 리소스 및 프롬프트 (Tools, Resources, Prompts)

### 2.1 도구 (Tools)

| 구분 | 도구명 | 설명 |
| :--- | :--- | :--- |
| **기업 종합 분석** | `analyze_company_comprehensive` | 국세청 세무상태 + 국민연금 고용/급여 + 금융위 재무제표 + 사내 RAG 이력 + DART 공시 융합 진단 |
| **전자공시 (DART)** | `search_dart_filings` | 기업별 최근 공시 보고서(사업·분기·주요사항보고서) 실시간 검색 |
| | `get_company_overview` | DART 기업 고유번호 기반 정식 법인 개요 및 사업자등록번호 조회 |
| **행정표준 & 주소** | `search_address` | 도로명/건물명 키워드 기반 정제 도로명주소, 지번, 5자리 우편번호 검색 |
| | `get_administrative_district`| 주소 문자열 기반 관할 시도, 시군구, 읍면동 행정구역코드 분리 |
| **사내 지식 (RAG)** | `rag_search_documents` | 사내 규정·기안문·매뉴얼 하이브리드(밀집+희소) 벡터 검색 |
| | `rag_ask_ai` | vLLM 고속 로컬 모델 기반 사내 지식 검증 질의응답 |
| | `rag_list_documents` | RAG 시스템 등록 문서 목록 페이징 조회 |
| | `rag_ingest_document` | AI 작성 분석 리포트·기안서를 사내 RAG 지식베이스에 실시간 색인 등록 |
| | `rag_get_document_detail` | 등록 문서 상세 메타데이터 및 청크 목록 단건 조회 |
| **조달청 나라장터 (PPS)** | `search_bid_announcements` | 나라장터 입찰공고 기간별 조회 |
| | `search_order_plans` | 공공기관의 연간 발주계획(사업명, 발주예정시기, 추정금액) 조회 |
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
| **워크스페이스 탐색** | `workspace_status` | 프로젝트 루트 디렉터리 상태 및 목록 조회 |
| | `list_project_files` | 디렉터리 상대 가시 파일 목록 조회 (깊이 제한) |
| | `read_project_file` | UTF-8 텍스트 파일 읽기 (256 KiB 샌드박스 제한) |
| | `grep_workspace_files` | 가시 파일 내 정규식/문자열 패턴 고속 검색 |
| | `workspace_project_summary` | 확장자별 파일 수 및 프로젝트 통계 요약 |
| **Go 초경량 런타임** | `health_ping` | Go 런타임 상태 및 하드웨어 가용 지표 즉시 응답 |
| | `greet` | Go MCP 표준 통신 검증용 도구 |

### 2.2 리소스 (Resources)
- `internal://rag/stats`: 사내 RAG-vLLM 색인 현황 및 서비스 상태 실시간 리소스
- `catalog://data-go/types`: 공공데이터포털 지원 데이터셋 유형 명세 리소스
- `dart://report-types`: DART 공시 유형 분류 코드 체계 리소스

### 2.3 프롬프트 (Prompts)
- `draft_internal_memo`: 사내 규정을 검색하여 표준 공문서·기안서 양식으로 초안을 작성하는 프롬프트
- `analyze_bid_proposal`: 나라장터 입찰공고를 분석하고 사내 RAG 실적을 매핑하여 제안 전략을 도출하는 프롬프트
- `audit_company_disclosure`: DART 최근 공시와 재무 상태를 분석하여 계약 리스크를 심사하는 프롬프트

---

## 3. 빠른 시작 및 클라이언트 등록

### 3.1 시스템 종합 진단
아래 명령으로 Node.js, Python, RAG-vLLM, API 키, 클라이언트 설정 상태를 원클릭 진단함:
```bash
./scripts/doctor.sh
```

### 3.2 실무 시나리오 E2E 벤치마크 실행
입찰공고 탐색부터 기업분석, 사내 RAG 검색, 문서 인제스트, TTL 캐시 성능을 일괄 검증함:
```bash
./scripts/benchmark-e2e.sh
```

### 3.3 Codex, Antigravity(agy), VS Code 원클릭 등록
아래 스크립트 실행으로 `~/.codex/config.toml`과 `~/.gemini/config/mcp_config.json`, `.vscode/mcp.json`, `internal-portal/.vscode/mcp.json`에 최신 게이트웨이가 자동 등록 및 갱신됨:
```bash
./scripts/register-clients.sh
```

### 3.4 단독 실행 테스트
- **통합 게이트웨이 실행**:
  ```bash
  ./scripts/run-mcp-gateway.sh
  ```
- **기업 종합 분석 실행**:
  ```bash
  ./scripts/run-corporate-intelligence.sh
  ```
- **DART 전자공시 실행**:
  ```bash
  ./scripts/run-dart-filings.sh
  ```
- **도로명주소 실행**:
  ```bash
  ./scripts/run-address-lookup.sh
  ```
- **RAG 단독 실행**:
  ```bash
  ./scripts/run-internal-rag.sh
  ```
- **HTTP 게이트웨이 (:8120) 실행 (OpenAPI 3.0 및 SSE 지원)**:
  ```bash
  npm run start:http-gateway
  ```
- **Go 초경량 MCP 클라이언트 검증**:
  ```bash
  ./scripts/run-mcp-go-client.sh
  ```

---

## 4. 보안 및 인증키 관리
- 실제 API 키는 프로젝트 루트의 `.env` 파일에서 관리되며 `.gitignore`에 등록되어 있어 저장소에 커밋되지 않음.
- 모든 API 요청 및 에러 로그는 `redact_sensitive()` 함수를 거쳐 인증키가 터미널이나 클라이언트에 평문 노출되지 않도록 마스킹 처리됨.
- 공공데이터포털 및 DART API 호출 시 `api_cache`(TTL In-Memory 캐시)가 적용되어 불필요한 일일 호출 쿼터 소모를 방지함.
- 워크스페이스 도구는 샌드박스를 적용하여 `.git`, `.venv`, `.env` 등 민감 파일 및 상위 디렉터리 심볼릭 링크 접근을 원천 차단함.
