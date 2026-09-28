# mcp-platform

회사 범용 MCP 서버, MCP 클라이언트, gateway, 데이터 커넥터를 한 프로젝트에서
관리합니다. 공공데이터는 여러 커넥터 중 하나이며, 향후 브라우저 자동화·수집기·
내부 시스템 커넥터를 추가할 수 있습니다.

## 구성

```text
src/
├─ servers/
│  ├─ workspace-tools.ts       # 외부 MCP 클라이언트가 호출하는 서버
│  └─ data-go-gateway.ts        # MCP 서버이면서 하위 서버용 gateway
└─ clients/
   └─ child-mcp-client.ts       # 하위 MCP 서버를 호출하는 재사용 클라이언트

python/mcp-runtime/             # Python MCP 실행 프로젝트
└─ mcp_platform/
   ├─ core/                      # 공통 HTTP·설정·오류 처리
   └─ servers/                   # 외부 데이터 소스별 MCP 서버
scripts/                        # 서버 launcher와 운영 스크립트
```

`servers/`는 도구를 외부에 제공하는 MCP 서버 코드이고, `clients/`는 다른 MCP
서버와 JSON-RPC로 통신하는 클라이언트 코드입니다. `data-go-gateway`는 외부에는
MCP 서버로 동작하면서 내부적으로는 `child-mcp-client`를 사용합니다.

### TypeScript MCP

기존 `workspace-tools` 서버는 로컬 workspace를 읽기 전용으로 탐색합니다.

```bash
npm install
npm run typecheck
npm run build
npm start
```

Codex 등록:

```bash
codex mcp add workspace-tools \
  --env MCP_WORKSPACE_ROOT=/home/kreverse/projects \
  -- node /home/kreverse/projects/mcp-platform/dist/servers/workspace-tools.js
```

### Python MCP runtime

Data.go.kr와 기타 외부 연동 코드는 다음 Python runtime에서 직접 관리합니다.

```text
python/mcp-runtime/mcp_platform/
```

기존 upstream 구현을 실행 의존성으로 사용하지 않고, 필요한 API 호출과 MCP
도구를 이 프로젝트의 공통 HTTP 계층과 여섯 개 모듈로 재작성했습니다. 원본
프로젝트 라이선스는 루트 [LICENSE](./LICENSE)에 두고, 원본 프로젝트 출처는
[THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)에 기록합니다.

Python 의존성 설치:

```bash
./scripts/setup-mcp-runtime.sh
```

여섯 서버는 하나의 Python 프로젝트와 가상환경을 공유하지만, 실행할 때는
각각 별도 stdio 프로세스로 뜹니다. 공통 코드는
`python/mcp-runtime/mcp_platform/core/common.py`에 있고, 서버별
수정은 `python/mcp-runtime/mcp_platform/servers/`의 `nps.py`, `nts.py`, `pps.py`,
`fsc.py`, `portal_catalog.py`, `food_safety.py`에서 합니다. 앞으로 외부 API를
추가할 때도
이 구조에 새 모듈과 launcher를 추가하면 됩니다.

현재 제공되는 서버는 다음과 같습니다.

| 서버 | 실행 스크립트 |
| --- | --- |
| NPS 사업장 가입정보 | `scripts/run-data-go-nps.sh` |
| NTS 사업자 진위확인 | `scripts/run-data-go-nts.sh` |
| 나라장터 조달정보 | `scripts/run-data-go-pps.sh` |
| 금융위원회 기업 재무정보 | `scripts/run-data-go-fsc.sh` |
| 공공데이터포털 카탈로그 검색 | `scripts/run-data-go-catalog.sh` |
| 식품안전나라 제품·품목·회수정보 | `scripts/run-data-go-food-safety.sh` |

실행 전 API 키를 환경변수로 설정합니다.

```bash
export DATA_GO_API_KEY='your-data-go-kr-api-key'
./scripts/run-data-go-nps.sh
```

공공데이터포털 키는 해당 API의 활용신청이 완료된 일반 인증키(Decoding)를
사용하는 것이 안전합니다. 식품안전나라 키는 여기에 사용할 수 없습니다.

식품안전나라 API는 별도 인증키와 서비스 이용신청이 필요합니다.
`FOOD_SAFETY_API_KEY`는 공공데이터포털의 `DATA_GO_API_KEY`와 다른 키입니다.

실제 API 키는 저장소에 커밋하지 마세요. 예시 파일은
`config/data-go.env.example`에 있습니다.

저장소 루트의 `.env`를 사용할 수도 있습니다. 이 파일은 `.gitignore`에
포함되어 있으며, 외부에서 전달한 `DATA_GO_API_KEY` 환경변수가 있으면 그
값을 우선합니다.

```bash
cp config/data-go.env.example .env
# .env의 DATA_GO_API_KEY 값을 실제 키로 수정
# 식품안전나라를 사용할 경우 FOOD_SAFETY_API_KEY도 별도로 입력
./scripts/run-data-go-gateway.sh
```

## Codex 등록 예시

API 키를 shell history나 소스 파일에 직접 넣지 않고, 현재 shell의 환경변수를
사용하는 예시입니다.

```bash
export DATA_GO_API_KEY='your-data-go-kr-api-key'

codex mcp add data-go-nts \
  -- /home/kreverse/projects/mcp-platform/scripts/run-data-go-nts.sh

codex mcp add data-go-pps \
  -- /home/kreverse/projects/mcp-platform/scripts/run-data-go-pps.sh
```

공공데이터포털 gateway 등록은 아래 gateway 섹션의 `data-go-portal` 명령을
사용합니다. 키는 저장소 루트 `.env`에서 자동으로 읽습니다.

## 하나의 Data.go.kr MCP gateway

여러 Python 서버를 하나의 MCP 프로세스로 사용하고 싶을 때는 gateway를
사용합니다. 기본 gateway는 NPS·FSC·공공데이터포털 카탈로그·식품안전나라를
실행하고, NTS와 나라장터는 별도 MCP로 분리합니다. gateway는 각 로컬 Python 서버를
내부 child process로 실행한 뒤
각 서버의 `tools/list` 결과를 하나의 도구 목록으로 합칩니다. API 클라이언트를
TypeScript로 옮기지 않고 Python 구현을 그대로 실행하므로 서버별 수정도
유지됩니다.

```bash
npm run build
export DATA_GO_API_KEY='your-data-go-kr-api-key'
./scripts/run-data-go-gateway.sh
```

기본값은 NPS·FSC·공공데이터포털 카탈로그·식품안전나라 서버를 시작합니다.
필요한 서버만 선택하려면:

```bash
export DATA_GO_SERVERS=nps,fsc,public_data_catalog,food_safety
./scripts/run-data-go-gateway.sh
```

gateway가 노출하는 도구명에는 서버 식별자가 붙습니다. 예를 들면
`data_go_nps_search_business` 형식입니다.

Codex 등록:

```bash
codex mcp add data-go-portal \
  -- /home/kreverse/projects/mcp-platform/scripts/run-data-go-portal.sh
```

개별 launcher는 장애 격리와 디버깅용으로 계속 사용할 수 있습니다.

## 소스 수정

`python/mcp-runtime/mcp_platform/servers/<server>.py`를 수정하면 다음 실행부터 바로
반영됩니다. PyPI 패키지나 `uvx`를 실행 경로로 사용하지 않으며, 의존성이
바뀌었을 때만 `./scripts/setup-mcp-runtime.sh`를 다시 실행하면 됩니다.

upstream 저장소는 구현 과정의 API·기능 참고 및 출처로만 기록되어 있고, 현재
실행 경로에는 포함되지 않습니다. 자세한 출처와 라이선스 안내는
[THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)를 확인하세요.

## 참고

- 원본 저장소: https://github.com/Koomook/data-go-mcp-servers
- 이 프로젝트는 한국 정부나 data.go.kr의 공식 프로젝트가 아닙니다.
- MCP 서버 코드의 라이선스와 API로 반환되는 공공데이터의 이용조건은
  별개이므로 각 API의 이용약관을 별도로 확인해야 합니다.
