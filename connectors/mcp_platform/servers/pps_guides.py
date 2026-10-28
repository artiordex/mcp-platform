"""나라장터 OpenAPI 도구의 MCP 리소스와 프롬프트 내용임"""

WORKFLOW_GUIDE = """# 나라장터 조달 데이터 분석 워크플로우

## 입찰 및 낙찰 조사
- `get_recent_bid_announcements`로 최근 입찰공고를 확인함
- `get_successful_bids_by_business_type`로 물품·외자·공사·용역별 낙찰 결과를 비교함
- `get_bid_detail`로 공고번호에 해당하는 상세 내용을 확인함

## 시장 및 제품 분석
- `get_procurement_statistics_by_year`로 연도별 공공조달 규모를 확인함
- `call_product_list_api`로 물품분류와 품목을 살펴봄
- `search_shopping_mall_products`로 MAS 계약 품목과 계약업체를 검색함

## 단계별 검색
1. API 작업과 필수 파라미터를 `get_all_api_services_info`와 `get_api_operations`로 확인함
2. 작은 페이지 크기로 첫 결과를 조회함
3. `call_api_with_pagination_support`의 전체 건수와 다음 페이지 정보를 확인함
4. 검색 범위가 너무 넓으면 기간, 기관, 기업, 물품분류 조건을 추가함
"""

PARAMETER_SELECTION_GUIDE = """# 나라장터 API 파라미터 선택 가이드

## 공통
- `operation`: 선택한 서비스에서 지원하는 오퍼레이션명임
- `num_of_rows`: 한 번에 받을 결과 수이며 초기 탐색에는 5~10건을 권장함
- `page_no`: 1부터 시작하는 페이지 번호임
- API별 추가 검색 조건은 `parameters` 객체에 나라장터 API 파라미터 이름으로 전달함

## 자주 쓰는 값
- 업무구분: `1` 물품, `2` 외자, `3` 공사, `5` 용역
- 기관구분: `1` 계약기관, `2` 수요기관
- 연도: `YYYY`; 기준월: `YYYYMM`; 일자: `YYYYMMDD`; 일시: `YYYYMMDDHHMM`

## 서비스별 검색 조건 예
- 입찰공고: `bidNtceBgnDt`, `bidNtceEndDt`
- 낙찰정보: `bsnsDivCd`, `opengBgnDt`, `opengEndDt`
- 계약정보: `cntrctCnclsBgnDate`, `cntrctCnclsEndDate`, `insttDivCd`, `insttCd`
- 조달통계: `srchBssYear`, `dminsttNm`, `corpNm`, `prdctClsfcNo`
- 물품목록: `upPrdctClsfcNo`, `prdctClsfcNo`, `prdctIdntNo`, `mnfctCorpNm`
- 종합쇼핑몰: `prdctClsfcNoNm`, `cntrctCorpNm`, `prdctIdntNo`, `dlvrReqNo`

서비스와 오퍼레이션 이름은 `get_api_operations`에서 확인함. 인증 키와 페이징 기본 파라미터는 서버가 관리함.
"""

API_PARAMETER_REQUIREMENTS = """# 나라장터 API 파라미터 요구사항

## 공공데이터개방표준서비스
- 입찰공고: `getDataSetOpnStdBidPblancInfo`; 조회 시작·종료 일시 권장
- 낙찰: `getDataSetOpnStdScsbidInfo`; 업무구분과 개찰 일시 범위 권장
- 계약: `getDataSetOpnStdCntrctInfo`; 계약체결일 범위와 기관 조건 선택
- 발주계획: `getDataSetOpnStdOrderPlanInfo`; 발주계획 시작·종료일 권장

## 공공조달통계정보서비스
- 14개 오퍼레이션 지원
- 기준연도 또는 기준월 범위, 수요기관·업체·물품 조건을 선택할 수 있음

## 물품목록정보서비스
- 12개 오퍼레이션 지원
- 상위 분류번호부터 단계적으로 조회하거나 품명·식별번호·제조업체로 검색함

## 종합쇼핑몰 품목정보 서비스
- 9개 오퍼레이션 지원
- 품명·계약업체·물품식별번호·납품요구번호 및 등록·변경일을 활용함

공통 페이징 값은 `num_of_rows`, `page_no`를 사용함. 빈 결과는 검색 조건을 완화하고, 결과가 많으면 페이지 단위로 조회함.
"""

PARAMETER_VALUE_EXAMPLES = """# 나라장터 파라미터 값 예시

- 업무구분: `1`(물품), `2`(외자), `3`(공사), `5`(용역)
- 기관구분: `1`(계약기관), `2`(수요기관)
- 조회구분: `1`(전체), `2`(신규), `3`(변경)
- 날짜·시간: `202610271430` (YYYYMMDDHHMM)
- 날짜: `20261027` (YYYYMMDD)
- 연월: `202610` (YYYYMM)
- 연도: `2026` (YYYY)
- 물품 검색어: `컴퓨터`, `프린터`, `소프트웨어`, `의료기기`
- 업체·기관 검색어: `삼성전자`, `교육부`, `서울시`

예시: `get_recent_bid_announcements(days_back=7)` 또는
`search_shopping_mall_products(product_name="컴퓨터", num_of_rows=10)`
"""

COMMON_SEARCH_PATTERNS = """# 나라장터에서 자주 쓰는 검색 패턴

## 시간별 조사
- 최근 입찰: `get_recent_bid_announcements(days_back=7)`
- 기간별 낙찰: `get_successful_bids_by_business_type`에 업무구분과 조회 기간 전달
- 연도별 조달 규모: `get_procurement_statistics_by_year`

## 품목과 업체 조사
- 물품분류 탐색: `call_product_list_api`에서 분류 조회 오퍼레이션 선택
- 쇼핑몰 품목 검색: `search_shopping_mall_products`에서 품명 또는 업체명 입력
- 납품요구 확인: `call_shopping_mall_api`에서 납품요구 오퍼레이션과 번호 사용

## 결과가 기대와 다를 때
1. 우선 `num_of_rows=5`로 응답 필드와 결과 유무를 확인함
2. 결과가 없으면 날짜 범위와 검색어를 넓힘
3. 결과가 많으면 기관·기업·물품분류 조건을 추가하고 다음 페이지를 확인함
"""

REAL_WORLD_QUERY_EXAMPLES = """# 나라장터 실전 질의 예제

## IT 장비 시장 진입 조사
1. 최근 입찰공고를 30일 범위로 조회함
2. 물품 업무구분의 낙찰 결과를 조회해 가격대를 파악함
3. 컴퓨터·프린터를 종합쇼핑몰에서 검색함
4. 연도별 조달통계로 시장 규모를 비교함

## 경쟁업체 및 품목 분석
- `search_shopping_mall_products(company_name="삼성전자", num_of_rows=15)`
- `search_shopping_mall_products(product_name="프린터", num_of_rows=20)`

## 특정 공고 제안 전략
- 공고번호로 `get_bid_detail`을 호출함
- `analyze_bid_proposal` 프롬프트로 참가요건, 평가요소, 내부 실적을 정리함
"""

EXPLORATION_GUIDES = {
    "small": {"num_of_rows": 10, "strategy": "첫 페이지 요청으로 구조를 확인함"},
    "medium": {"num_of_rows": 5, "strategy": "2~3회 페이징하며 조건을 조정함"},
    "large": {"num_of_rows": 3, "strategy": "작은 페이지로 전체 규모를 파악한 뒤 나누어 조회함"},
}
