# MCP Platform (사내 통합 MCP 게이트웨이 및 데이터 커넥터)

사내 표준 AI 클라이언트(Codex, Claude Desktop, Cursor, VS Code 등)에게 공공데이터(국민연금, 국세청, 조달청 나라장터, 금융위, DART 전자공시, 행정안전부 도로명주소, 중기부 지원사업, 특허청 KIPRIS), 사내 RAG-vLLM 지식 검색, 로컬 워크스페이스 도구를 단일 엔드포인트로 통합 제공하는 단일 사용자용 MCP 프로토타입 플랫폼임.

---

## 1. 아키텍처 및 통신 방식 (Architecture & Transports)

본 플랫폼은 공식 MCP TypeScript SDK(`@modelcontextprotocol/server`, `@modelcontextprotocol/client`)를 기반으로 설계되었으며, `awesome-mcp-clients` 목록 중 실제 동작을 검증한 클라이언트(Codex, Claude Desktop, Cursor, VS Code)와의 연동을 지원함.

```text
mcp-platform/
├── config/
│   ├── mcp-servers.example.json   # 게이트웨이 예시 설정 (활성 서버, 쓰기 정책, 도구 선택)
│   └── clients/                   # 클라이언트 연동 템플릿 (Codex, Claude Desktop, Cursor, VS Code)
├── src/                           # TypeScript 게이트웨이 및 클라이언트
│   ├── servers/
│   │   ├── mcp-gateway.ts         # 다중 서버 도구·리소스·프롬프트 통합 게이트웨이 (stdio)
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
├── cmd/ & internal/               # Go 초경량 stdio MCP 런타임 (greet, health_ping, system_metrics)
└── scripts/                       # 실행 및 자동화 스크립트
    ├── mcp-cli.sh                 # 터미널 전용 관리 도구
    ├── doctor.sh                  # 17개 항목 시스템 종합 진단 도구
    ├── benchmark-e2e.sh           # 6대 실무 시나리오 E2E 파이프라인 검증 스크립트
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
  - 도구명이 생성/수정/삭제/인제스트(`create`, `update`, `delete`, `ingest`, `write` 등)를 포함하거나 `readOnlyHint: false`인 경우 쓰기 도구로 분류함.
  - 쓰기 도구는 기본적으로 비활성화되며, `MCP_ALLOW_WRITE_TOOLS=true` 환경변수 또는 서버별 설정(`allowWriteTools: true`)이 명시된 경우에만 활성화됨.
  - SDK 표준 어노테이션(`readOnlyHint: true/false`, `idempotentHint: true`)을 보존하여 LLM 에이전트의 안전한 호출을 보장함.

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

---

## 3. HTTP 게이트웨이 및 보안 기본값 (HTTP Gateway & Security Defaults)

공식 MCP SDK의 `WebStandardStreamableHTTPServerTransport`를 채택하여 표준 Streamable HTTP 전송을 제공하며, REST 관리 기능은 `/api/*` 경로로 완전히 분리함.

### 3.1 주요 보안 기본값 (Security Defaults)
1. **기본 바인딩 주소 (`127.0.0.1`)**:
   - 외부 네트워크에 무단 노출되지 않도록 기본 바인딩 주소를 루프백(`127.0.0.1`)으로 제한함.
   - 비루프백 주소(`0.0.0.0` 또는 공인 IP)로 바인딩 시 `MCP_HTTP_BEARER_TOKEN`이 설정되지 않으면 서버 시작을 즉시 거부함.
2. **엄격한 Origin 및 Host 헤더 검증**:
   - `Access-Control-Allow-Origin: *` 와일드카드를 완전히 제거함.
   - `@modelcontextprotocol/server`의 `validateHostHeader`, `validateOriginHeader`를 사용하여 허용된 Origin 및 Host만 수락하며, 불일치 시 `403 Forbidden`으로 차단함.
3. **요청 본문 크기 및 타임아웃 제한**:
   - HTTP 요청 본문은 최대 1MB(`MAX_BODY_BYTES`)로 제한되며 초과 시 `413 Payload Too Large`를 반환함.
   - 요청 처리 시간은 최대 30초로 제한되어 슬로우로리스(Slowloris) 공격을 차단함.
4. **HTTP 워크스페이스 파일 격리**:
   - 원격 HTTP 환경에서 로컬 파일 노출을 방지하기 위해 워크스페이스 도구는 기본 비활성화됨.
   - 사용자가 명시적으로 `MCP_ENABLE_WORKSPACE_HTTP=true`를 설정한 경우에만 엄격한 경로 탈출 방지 샌드박스를 적용하여 노출함.
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

## 4. 검증된 클라이언트 및 설정 등록 (Verified Clients)

본 저장소는 다음 4종의 주요 클라이언트에 대해 실제 설정 파일 파싱 및 정상 연결을 검증함.

| 클라이언트 | 연결 방식 | 설정 파일 위치 | 지원 상태 |
| :--- | :--- | :--- | :--- |
| **Codex** | stdio (`run-mcp-gateway.sh`) | `~/.codex/config.toml` | 직접 검증 완료 |
| **Claude Desktop** | stdio (`run-mcp-gateway.sh`) | `~/.config/Claude/claude_desktop_config.json` | 직접 검증 완료 |
| **Cursor** | stdio (`run-mcp-gateway.sh`) | `~/.cursor/mcp.json` | 직접 검증 완료 |
| **VS Code / Cline** | stdio (`run-mcp-gateway.sh`) | `.vscode/mcp.json` | 직접 검증 완료 |

### 안전한 클라이언트 설정 병합 (`register-clients.sh`)
제공되는 등록 스크립트는 기존 설정 파일에 존재하는 다른 MCP 서버나 사용자 정의 설정을 절대로 덮어쓰거나 삭제하지 않음. `scripts/merge-client-config.py`를 통해 `mcp-platform` 관리 대상 항목만 선별적으로 추가 및 갱신함.

```bash
# 검증된 클라이언트에 mcp-platform 안전 병합 등록
./scripts/register-clients.sh
```

---

## 5. 빠른 시작 및 환경설정 (Quickstart)

### 5.1 사전 준비
```bash
# 1. 의존성 설치 및 TypeScript 빌드
npm install
npm run build

# 2. Python 커넥터 가상환경 의존성 설치
python3 -m venv .venv
source .venv/bin/activate
pip install -e connectors/

# 3. 게이트웨이 설정 파일 준비 (예시 복사)
cp config/mcp-servers.example.json config/mcp-servers.json
```

### 5.2 환경변수 안내
| 환경변수명 | 기본값 | 설명 |
| :--- | :--- | :--- |
| `MCP_SERVERS_CONFIG` | `config/mcp-servers.json` | 게이트웨이 서버 목록 설정 파일 경로임 |
| `MCP_ALLOW_WRITE_TOOLS` | `false` | 쓰기 작업 도구 활성화 여부 (보안 기본값: 비활성화) |
| `MCP_HTTP_HOST` | `127.0.0.1` | HTTP 게이트웨이 바인딩 주소 (비루프백 지정 시 토큰 필수) |
| `MCP_HTTP_PORT` | `8120` | HTTP 게이트웨이 서비스 포트임 |
| `MCP_HTTP_BEARER_TOKEN` | (선택) | HTTP `/mcp` 통신용 Bearer 인증 토큰임 |
| `MCP_ADMIN_TOKEN` | (선택) | `/api/admin/*` 관리자 경로 호출용 인증 토큰임 |
| `MCP_ALLOWED_HOSTS` | `localhost,127.0.0.1` | 허용할 Host 헤더 목록임 |
| `MCP_ALLOWED_ORIGINS` | `localhost,127.0.0.1` | 허용할 CORS Origin 목록임 |
| `MCP_ENABLE_WORKSPACE_HTTP` | `false` | HTTP 환경에서 워크스페이스 도구 노출 여부임 |

### 5.3 게이트웨이 실행
```bash
# 전체 통합 게이트웨이 실행 (stdio)
./scripts/run-mcp-gateway.sh

# 공공데이터 전용 게이트웨이 실행 (stdio)
./scripts/run-data-go-portal.sh

# 표준 Streamable HTTP 게이트웨이 실행 (:8120)
npm run start:http-gateway
```

### 5.4 테스트 및 시스템 진단
```bash
# TypeScript 및 단위/통합 테스트 실행 (10개 테스트)
npm test

# Python FastMCP 커넥터 단위 테스트 실행 (43개 테스트)
.venv/bin/pytest connectors/tests -v

# 시스템 종합 진단 도구 실행
./scripts/doctor.sh

# 6대 실무 시나리오 E2E 파이프라인 벤치마크
./scripts/benchmark-e2e.sh
```

---

## 6. 알려진 제한 사항 (Known Limitations)

1. **단일 사용자 로컬 프로토타입**:
   - 본 프로젝트는 단일 개발자 또는 내부 엔지니어링 검증을 위한 로컬 프로토타입 수준으로 구현되었음.
   - 멀티테넌트 격리, 사용자별 OAuth2/OIDC 인가, 조직 권한 관리(RBAC)는 포함하지 않음.
2. **클라이언트 생태계 범위**:
   - `awesome-mcp-clients`는 커뮤니티 클라이언트 목록이며, 본 저장소는 실제 설정 파일과 동작을 검증한 Codex, Claude Desktop, Cursor, VS Code 4종을 우선 지원 대상으로 관리함.
3. **외부 API 쿼터 의존성**:
   - 공공데이터포털, DART, KIPRIS 커넥터는 실제 외부 정부 시스템의 일일 호출 쿼터에 의존하므로 사내 개발 환경에서는 TieredCache(L1 메모리 + L2 SQLite WAL) 영속 계층을 적극 활용해야 함.
