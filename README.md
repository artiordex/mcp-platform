# MCP Platform (사내 통합 MCP 게이트웨이 및 데이터 커넥터)

사내 표준 AI 클라이언트(Codex, Claude Desktop, Cursor, VS Code 등)에게 공공데이터(국민연금, 국세청, 조달청 나라장터, 금융위, DART 전자공시, 행정안전부 도로명주소, 중기부 지원사업, 특허청 KIPRIS), 사내 RAG-vLLM 지식 검색, 로컬 워크스페이스 도구를 단일 엔드포인트로 통합 제공하는 단일 사용자용 MCP 프로토타입 플랫폼임.

---

## 1. 아키텍처 및 통신 방식 (Architecture & Transports)

본 플랫폼은 공식 MCP TypeScript SDK(`@modelcontextprotocol/server`, `@modelcontextprotocol/client`)를 기반으로 구성됨. Codex, Claude Desktop, Cursor, VS Code 설정 템플릿을 제공하며, 클라이언트 버전과 실행 환경에 따라 설치 후 연결 확인이 필요함.

```text
mcp-platform/
├── config/
│   ├── mcp-servers.example.json   # 게이트웨이 예시 설정 (활성 서버, 쓰기 정책, 도구 선택)
│   └── clients/                   # 클라이언트 연동 템플릿 (Codex, Claude Desktop, Cursor, VS Code)
├── src/                           # TypeScript 게이트웨이 및 클라이언트
│   ├── servers/
│   │   ├── mcp-gateway.ts         # 다중 서버 게이트웨이 코어 및 stdio 실행기
│   │   ├── data-go-gateway.ts     # 공공데이터 및 RAG 12대 커넥터 통합 게이트웨이 (stdio)
│   │   ├── http-gateway.ts        # 공식 SDK 기반 Streamable HTTP 게이트웨이 (:8120/mcp, REST /api/*)
│   │   └── workspace-tools.ts     # 로컬 프로젝트 파일 탐색 및 코드 분석 (읽기 전용 샌드박스)
│   └── clients/
│       └── child-mcp-client.ts    # 자식 MCP 프로세스 생명주기 및 리소스/프롬프트 관리자
├── connectors/                    # Python FastMCP 데이터 커넥터
│   └── mcp_platform/
│       ├── core/                  # 공통 HTTP, 응답 정규화, 2계층 영속 캐시(TieredCache)
│       ├── cli/                   # mcp-cli 터미널 명령 처리
│       └── servers/               # 12대 커넥터 (기업분석, DART, 도로명주소, SMES, 특허청, RAG 등)
├── cmd/ & internal/               # Go 초경량 stdio MCP 런타임 및 고성능 병렬 배치 수집기
│   ├── cmd/mcp-go-server/         # Go stdio MCP 서버 엔트리포인트 (6개 도구 등록)
│   ├── cmd/batch-collector/       # 고루틴 병렬 수집기 및 벤치마크 CLI 엔트리포인트
│   ├── internal/batchcollector/   # 고루틴 워커 풀, 입찰공고 병렬 수집, 사업자등록 병렬 검증
│   └── internal/mcpserver/        # Go MCP 도구 구현체 (bids, corporate, benchmark, metrics 등)
└── scripts/                       # 실행 및 자동화 스크립트
    ├── mcp-cli.sh                 # 터미널 전용 관리 도구
    ├── doctor.sh                  # 20개 항목 시스템 종합 진단 도구
    ├── benchmark-e2e.sh           # 7대 실무 시나리오 E2E 파이프라인 검증 스크립트
    ├── register-clients.sh        # 클라이언트 설정 보존 병합 스크립트
    ├── merge-client-config.py     # JSON/TOML 안전 병합 유틸리티
    └── run-*.sh                   # 개별 서버 및 게이트웨이 단독 실행기
```

---

## 2. 통합 게이트웨이 전달 기능 (Forwarding Specification)

통합 게이트웨이(`mcp-gateway.ts`, `data-go-gateway.ts`)는 연결된 모든 하위 서버의 도구, 리소스, 프롬프트를 네임스페이스 충돌 없이 상위 MCP 클라이언트로 전달함.

### 2.1 도구 (Tools) 전달 및 쓰기 안전 정책
- **네임스페이스**: `mcp_${serverId}_${toolName}` 또는 `data_go_${serverId}_${toolName}` 규칙을 강제 적용하여 서버 간 도구명 충돌을 원천 방지함.
- **메타데이터 보존**: 하위 서버의 `description`, `inputSchema`를 공식 SDK 규격으로 보존함.
- **안전성 어노테이션 및 쓰기 정책**:
  - 이름에 변경 동작이 드러나거나 `readOnlyHint: false`인 도구는 쓰기 도구로 분류함. 변경 도구명으로 보이지 않더라도 명시적 `readOnlyHint: true` 또는 서버별 `readOnlyTools` 항목이 없으면 기본 차단함.
  - 쓰기 도구와 분류되지 않은 도구는 기본 비활성화이며, `MCP_ALLOW_WRITE_TOOLS=true` 또는 서버별 `allowWriteTools: true`를 지정해야 활성화됨. `config/mcp-servers.example.json`에는 현재 조회 도구 목록을 서버별로 명시함.
  - 원격 서버는 `enabledTools` 허용 목록을 반드시 지정해야 하며, 원격 HTTP 연결에는 HTTPS를 사용해야 함 (평문 HTTP는 루프백 주소만 허용됨). 로컬 명령 서버도 신뢰할 수 있는 실행 파일만 등록해야 함.

### 2.2 리소스 (Resources) 전달
- **네임스페이스 URI**: `mcp://${serverId}/${uri_path}` 규칙으로 URI 충돌을 방지함.
- 제공 리소스:
  - `mcp://system/servers`: 등록된 하위 MCP 서버들의 실제 상태(`ready` vs `error`), 활성 도구 수, 리소스 수, 프롬프트 수 및 오류 메시지를 반환하는 진단 리소스임.
  - `mcp://internal_rag/internal/rag/stats`: 사내 RAG-vLLM 색인 및 서비스 상태 리소스임.
  - `mcp://data_go_catalog/catalog/data-go/types`: 공공데이터포털 데이터셋 분류 체계 리소스임.
  - `mcp://dart_filings/dart/report-types`: DART 공시 보고서 분류 체계 리소스임.
  - `mcp://smes_programs/smes/categories`: 중기부 지원사업 7대 분류 체계 리소스임.
  - `mcp://kipris_patents/kipris/ipc-sections`: 특허청 IPC 8대 섹션 표준 체계 리소스임.

### 2.3 프롬프트 (Prompts) 전달
- **네임스페이스 이름**: `mcp_${serverId}_${promptName}` 또는 `data_go_${serverId}_${promptName}`로 노출함.
- **인자 스키마 보존**: 프롬프트 인자(`arguments`)를 Zod 스키마로 변환하여 상위 클라이언트에서 인자 힌트 및 완성 기능을 온전히 지원함.
- 제공 프롬프트:
  - `mcp_internal_rag_draft_internal_memo`: 사내 규정을 검색하여 표준 기안문 양식을 작성하는 프롬프트임.
  - `mcp_data_go_pps_analyze_bid_proposal`: 나라장터 입찰공고 분석 및 제안 전략 수립 프롬프트임.
  - `mcp_dart_filings_audit_company_disclosure`: DART 공시 및 재무 상태 분석 프롬프트임.
  - `mcp_smes_programs_match_company_policy_funds`: 기업 제원 맞춤형 정부지원사업 매칭 프롬프트임.
  - `mcp_kipris_patents_analyze_patent_competitiveness`: 기업 특허 포트폴리오 기술 경쟁력 분석 프롬프트임.

### 2.4 장애 격리 (Fault Tolerance)
- 특정 하위 서버가 미기동되거나 오류가 발생하더라도 전체 게이트웨이가 비정상 종료되지 않고 정상 서버들만 안전하게 서비스함.
- 모든 서버를 무조건 `ready`로 표시하지 않으며, `mcp://system/servers` 리소스 및 `/api/servers` 엔드포인트에 실제 상태(`ready`, `error`, `disabled`)와 구체적인 오류 원인을 기록함.

### 2.5 Go 병렬 처리 데모 및 초경량 런타임
Go 런타임은 MCP 서버 예제와 합성 데이터 기반 병렬 처리 데모를 제공함. 현재 나라장터 공고 도구는 실제 API를 호출하지 않으며, 벤치마크 수치는 합성 지연 작업 결과로 실제 처리량을 의미하지 않음.
- **제공 도구**:
  - `batch_collect_bids`: 합성 공고 샘플을 생성해 병렬 처리와 중복 제거 흐름을 시연함.
  - `batch_validate_corporate`: 사업자등록번호 체크섬 형식만 확인함. 실제 사업자 상태와 과세 유형은 조회하지 않음.
  - `benchmark_parallel_collector`: 고정 지연 작업에서 순차 처리와 병렬 처리 시간을 비교하는 로컬 데모임.
  - `greet`: 호출 클라이언트 식별 및 환영 메시지를 반환함.
  - `health_ping`: 초경량 무상태 헬스체크 핑을 수행함.
  - `system_metrics`: 호스트 CPU 코어 수, 고루틴 활성 수, 메모리 할당량 등 시스템 런타임 지표를 반환함.
- **독립 실행기**:
  - `cmd/batch-collector/main.go`를 통해 MCP 연결 없이도 터미널에서 단독 벤치마크 및 병렬 수집 테스트가 가능함.

---

## 3. HTTP 게이트웨이 및 보안 기본값 (HTTP Gateway & Security Defaults)

공식 MCP SDK의 `WebStandardStreamableHTTPServerTransport`를 채택하여 표준 Streamable HTTP 전송을 제공함. `/mcp`는 stdio와 같은 `MCP_SERVERS_CONFIG` 하위 서버를 통합하며, REST 관리 기능은 `/api/*` 경로로 분리함.

### 3.1 주요 보안 기본값 (Security Defaults)
1. **기본 바인딩 주소 (`127.0.0.1`)**:
   - 외부 네트워크에 무단 노출되지 않도록 기본 바인딩 주소를 루프백(`127.0.0.1`)으로 제한함.
   - 비루프백 주소(`0.0.0.0` 또는 공인 IP)로 바인딩 시 `MCP_HTTP_BEARER_TOKEN`이 설정되지 않으면 서버 시작을 즉시 거부함.
   - `/mcp`는 `MCP_HTTP_BEARER_TOKEN`이 설정된 경우 해당 토큰을 요구함. `/api/health`를 제외한 관리 API는 `MCP_HTTP_BEARER_TOKEN` 또는 `MCP_ADMIN_TOKEN`으로 인증하며, 캐시 초기화에는 관리자 토큰을 요구함. 관리자 토큰의 기본값은 `MCP_HTTP_BEARER_TOKEN`임.
2. **엄격한 Origin 및 Host 헤더 검증**:
   - `Access-Control-Allow-Origin: *` 와일드카드를 완전히 제거함.
   - `@modelcontextprotocol/server`의 `validateHostHeader`, `validateOriginHeader`를 사용하여 허용된 Origin 및 Host만 수락하며, 불일치 시 `403 Forbidden`으로 차단함.
3. **요청 본문 크기 및 타임아웃 제한**:
   - HTTP 요청 본문은 최대 1MB(`MAX_BODY_BYTES`)로 제한되며 초과 시 `413 Payload Too Large`를 반환함.
   - 요청 헤더와 본문 수신은 30초로 제한됨. 이 제한은 MCP 도구 실행 시간 제한이 아님.
4. **HTTP 워크스페이스 파일 격리**:
   - 원격 HTTP 환경에서 로컬 파일 노출을 방지하기 위해 워크스페이스 도구는 기본 비활성화됨.
   - 사용자가 명시적으로 `MCP_ENABLE_WORKSPACE_HTTP=true`를 설정한 경우에만 엄격한 경로 탈출 방지 샌드박스를 적용하여 노출함.
   - 파일 검색은 리터럴 문자열만 허용하고 검색 파일 수, 총 바이트, 반환 결과 크기에 상한을 적용함.
5. **관리자 작업 분리**:
   - 원격 호출 경로의 캐시 초기화(`/cache/clear`)는 기본 차단되며, 인증된 관리자 경로(`POST /api/admin/cache/clear`)에서 유효한 Bearer 토큰(`MCP_ADMIN_TOKEN` 또는 `MCP_HTTP_BEARER_TOKEN`)이 제공되어야만 실행됨.

### 3.2 HTTP 엔드포인트 명세
- **표준 MCP 엔드포인트**:
  - `POST /mcp`: JSON-RPC 2.0 프로토콜 메시지(initialize, tools/list, tools/call, resources/list, resources/read, prompts/list, prompts/get) 처리
  - `GET /mcp`: 표준 MCP SSE 이벤트 스트림 연결
  - `DELETE /mcp`: 표준 MCP 세션 종료
- **REST 관리 엔드포인트 (`/api/*`)**:
  - `GET /api/health`: 서비스 상태 및 가동 시간 (JSON)
  - `GET /api/servers`: 등록된 하위 MCP 서버들의 실제 상태 목록 (JSON)
  - `GET /api/tools`: 등록 도구 명세 (JSON)
  - `GET /api/cache/stats`: 2계층 영속 캐시 적재 현황 (JSON)
  - `POST /api/admin/cache/clear`: 관리자 전용 영속 캐시 초기화 (Bearer 인증 필수)
  - `GET /api/doctor`: 시스템 종합 진단 리포트 (Text)
  - `GET /api/openapi.json`: OpenAPI 3.0 사양서 (JSON)
  - `GET /api/heartbeat-stream`: 단순 연결 유지용 SSE 스트림

---

## 4. 클라이언트 설정 템플릿 및 등록

다음 주요 클라이언트용 설정 템플릿과 등록 스크립트를 제공함. 등록 후 각 클라이언트에서 서버 상태를 확인해야 함.

| 클라이언트 | 연결 방식 | 설정 파일 위치 | 지원 상태 |
| :--- | :--- | :--- | :--- |
| **Codex** | stdio (`run-mcp-gateway.sh`) | `~/.codex/config.toml` | 템플릿 제공 |
| **Claude Desktop** | stdio (`run-mcp-gateway.sh`) | `~/.config/Claude/claude_desktop_config.json` | 템플릿 제공 |
| **Cursor** | stdio (`run-mcp-gateway.sh`) | `~/.cursor/mcp.json` | 템플릿 제공 |
| **VS Code** | stdio (`run-mcp-gateway.sh`) | `.vscode/mcp.json` | VS Code 형식 템플릿 제공 |

### 안전한 클라이언트 설정 병합 (`register-clients.sh`)
제공되는 등록 스크립트는 `mcp-platform` 관리 항목만 갱신하고 다른 서버 설정은 보존함. JSON 설정 파일을 파싱할 수 없으면 덮어쓰지 않고 중단함.

```bash
# 클라이언트 설정에 mcp-platform 등록
./scripts/register-clients.sh
```

---

## 5. 빠른 시작 및 환경설정 (Quickstart)

### 5.1 사전 준비
```bash
# 1. 잠금 파일 기준 의존성 설치 및 TypeScript 빌드
npm ci
npm run build

# 2. Python 커넥터 가상환경 의존성 설치
./scripts/setup-mcp-runtime.sh

# 3. API 키 환경 파일 준비
cp config/data-go.env.example .env
# .env 파일에 발급받은 키 입력

# 4. 게이트웨이 설정 파일 준비 (예시 복사)
cp config/mcp-servers.example.json config/mcp-servers.json
```

### 5.2 환경변수 안내
| 환경변수명 | 기본값 | 설명 |
| :--- | :--- | :--- |
| `MCP_SERVERS_CONFIG` | `config/mcp-servers.json` | 게이트웨이 서버 목록 설정 파일 경로임 |
| `MCP_ALLOW_WRITE_TOOLS` | `false` | 쓰기 작업 도구 활성화 여부 (보안 기본값: 비활성화) |
| `MCP_HTTP_HOST` | `127.0.0.1` | HTTP 게이트웨이 바인딩 주소 (비루프백 지정 시 토큰 필수) |
| `MCP_HTTP_PORT` | `8120` | HTTP 게이트웨이 서비스 포트임 |
| `MCP_HTTP_BEARER_TOKEN` | (선택) | 원격 바인딩, `/mcp`, 관리 API 인증용 토큰임 (`/api/health` 제외) |
| `MCP_ADMIN_TOKEN` | `MCP_HTTP_BEARER_TOKEN` | 관리 API 인증 토큰이며 캐시 초기화 요청에 필요함 |
| `MCP_WORKSPACE_ROOT` | mcp-platform 저장소 루트 | 클라이언트 등록 시 워크스페이스 도구의 읽기 범위임 |
| `MCP_ALLOWED_HOSTS` | `localhost,127.0.0.1` | 허용할 Host 헤더 목록임 |
| `MCP_ALLOWED_ORIGINS` | `localhost,127.0.0.1` | 허용할 CORS Origin 목록임 |
| `MCP_ENABLE_WORKSPACE_HTTP` | `false` | HTTP 환경에서 워크스페이스 도구 노출 여부임 |

### 5.3 게이트웨이 실행
```bash
# 전체 통합 게이트웨이 실행 (stdio, 먼저 빌드와 config 준비 필요)
./scripts/run-mcp-gateway.sh

# 공공데이터 전용 게이트웨이 실행 (stdio)
./scripts/run-data-go-portal.sh

# stdio와 같은 커넥터를 노출하는 Streamable HTTP 게이트웨이 실행 (:8120)
npm run start:http-gateway
```

### 5.4 테스트 및 시스템 진단
```bash
# TypeScript 및 단위/통합 테스트 실행
npm test

# Go 초경량 런타임 및 병렬 수집기 단위 테스트 실행
go test -v ./...

# Python FastMCP 커넥터 단위 테스트 실행
.venv/bin/pytest connectors/tests -v

# 시스템 종합 진단 도구 실행 (20개 항목 점검)
./scripts/doctor.sh

# 7대 실무 시나리오 E2E 파이프라인 벤치마크 (Go 병렬 수집 포함)
./scripts/benchmark-e2e.sh
```

---

## 6. 알려진 제한 사항 (Known Limitations)

1. **단일 사용자 로컬 프로토타입**:
   - 본 프로젝트는 단일 개발자 또는 내부 엔지니어링 검증을 위한 로컬 프로토타입 수준으로 구현되었음.
   - 멀티테넌트 격리, 사용자별 OAuth2/OIDC 인가, 조직 권한 관리(RBAC)는 포함하지 않음.
2. **클라이언트 생태계 범위**:
   - 클라이언트 설정 템플릿을 제공하지만 클라이언트 버전별 동작은 설치 환경에서 확인해야 함.
3. **외부 API 쿼터 의존성**:
   - 공공데이터포털, DART, KIPRIS 커넥터는 실제 외부 정부 시스템의 일일 호출 쿼터에 의존하므로 사내 개발 환경에서는 TieredCache(L1 메모리 + L2 SQLite WAL) 영속 계층을 적극 활용해야 함.
