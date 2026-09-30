# =============================================================================
# 파일명: test_smes.py
# 경로: connectors/tests/test_smes.py
# 목적: 중소벤처기업부 기업마당 지원사업 커넥터 기능 단위 테스트임
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""중소벤처기업부 기업마당 지원사업 커넥터의 도구, 자원, 프롬프트 동작을 검증함"""

import asyncio

from mcp_platform.servers import smes


def run_async(coro):
    """비동기 코루틴을 동기 방식으로 실행함"""
    return asyncio.run(coro)


def test_search_support_programs_success(monkeypatch):
    """기업마당 지원사업 목록 조회가 정상 파싱되는지 검증함"""
    fake_payload = {
        "totalCount": 2,
        "jsonArray": [
            {
                "pblancId": "PBLN_20260901_001",
                "pblancNm": "2026년 AI 바우처 지원사업 공고",
                "pldirExatNm": "기술 (R&D)",
                "excAgency": "정보통신산업진흥원",
                "reqstBeginEndDe": "2026-09-01 ~ 2026-10-31",
                "trgetNm": "중소·벤처기업",
                "pblancUrl": "https://www.bizinfo.go.kr/detail?id=PBLN_001",
            },
            {
                "pblancId": "PBLN_20260901_002",
                "pblancNm": "2026년 글로벌 강소기업 육성사업",
                "pldirExatNm": "수출",
                "excAgency": "중소벤처기업진흥공단",
                "reqstBeginEndDe": "2026-09-10 ~ 2026-10-20",
                "trgetNm": "수출 중소기업",
                "pblancUrl": "https://www.bizinfo.go.kr/detail?id=PBLN_002",
            },
        ],
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return fake_payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

        async def get(self, url, params=None):
            return FakeResponse()

    monkeypatch.setattr(smes.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    res = run_async(smes.search_support_programs(keyword="AI", category="TECH", page_no=1, num_of_rows=10))
    assert res["success"] is True
    assert res["total_count"] == 2
    assert len(res["items"]) == 2
    assert res["items"][0]["pblanc_id"] == "PBLN_20260901_001"
    assert "AI 바우처" in res["items"][0]["title"]


def test_get_support_program_detail_success(monkeypatch):
    """기업마당 지원사업 상세 조회가 정상 수행되는지 검증함"""
    fake_detail_payload = {
        "jsonArray": [
            {
                "pblancId": "PBLN_20260901_001",
                "pblancNm": "2026년 AI 바우처 지원사업 공고",
                "bsnsCn": "AI 솔루션 도입을 희망하는 중소기업 대상 바우처 지원",
                "trgetNm": "중소기업기본법 제2조에 따른 중소기업",
                "sportCn": "기업당 최대 2억원 한도 지원",
                "reqstMthd": "온라인 포털 접수",
                "inqryTelno": "043-931-5000",
                "pblancUrl": "https://www.bizinfo.go.kr/detail?id=PBLN_001",
            }
        ]
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return fake_detail_payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

        async def get(self, url, params=None):
            return FakeResponse()

    monkeypatch.setattr(smes.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    detail = run_async(smes.get_support_program_detail(pblanc_id="PBLN_20260901_001"))
    assert detail["success"] is True
    assert detail["pblanc_id"] == "PBLN_20260901_001"
    assert "최대 2억원" in detail["support_content"]
    assert detail["contact_info"] == "043-931-5000"


def test_get_support_program_detail_empty(monkeypatch):
    """빈 결과 응답 시 오류 메시지를 반환하는지 검증함"""
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"jsonArray": []}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

        async def get(self, url, params=None):
            return FakeResponse()

    monkeypatch.setattr(smes.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    detail = run_async(smes.get_support_program_detail(pblanc_id="NOT_EXIST_ID"))
    assert detail["success"] is False
    assert "찾을 수 없음" in detail["error"]


def test_get_support_categories_resource():
    """자원(Resource)으로 기업마당 지원분야 카테고리 명세가 제공되는지 검증함"""
    doc = smes.get_support_categories()
    assert "7대 지원분야 체계" in doc
    assert "TECH" in doc
    assert "STARTUP" in doc


def test_match_company_policy_funds_prompt():
    """맞춤형 지원사업 기안 프롬프트가 올바른 항목을 포함하는지 검증함"""
    prompt = smes.match_company_policy_funds(
        company_name="테스트테크(주)",
        business_sector="소프트웨어 개발",
        employee_count=15,
        focus_area="AI 솔루션 R&D",
    )
    assert "테스트테크(주)" in prompt
    assert "소프트웨어 개발" in prompt
    assert "15인" in prompt
    assert "사내 RAG 문서" in prompt
