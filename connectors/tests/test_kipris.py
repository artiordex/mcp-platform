# =============================================================================
# 파일명: test_kipris.py
# 경로: connectors/tests/test_kipris.py
# 목적: 특허청 KIPRIS 특허·실용신안 커넥터 단위 테스트임
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""특허청 KIPRIS 커넥터의 도구, 자원, 프롬프트 동작을 검증함"""

import asyncio

from mcp_platform.servers import kipris


def run_async(coro):
    """비동기 코루틴을 동기 방식으로 실행함"""
    return asyncio.run(coro)


def test_search_patents_validation():
    """출원인과 키워드가 모두 비어 있을 때 유효성 오류를 반환하는지 검증함"""
    res = run_async(kipris.search_patents(applicant="", keyword=""))
    assert res["success"] is False
    assert "필수임" in res["error"]


def test_search_patents_success_xml(monkeypatch):
    """KIPRIS XML 형식 응답이 올바르게 파싱되는지 검증함"""
    xml_sample = """<?xml version="1.0" encoding="UTF-8"?>
    <response>
        <header>
            <resultCode>00</resultCode>
            <resultMsg>NORMAL SERVICE.</resultMsg>
        </header>
        <body>
            <items>
                <item>
                    <applicationNumber>1020250012345</applicationNumber>
                    <inventionTitle>대규모 언어 모델 기반의 지능형 특허 문서 검색 시스템</inventionTitle>
                    <applicantName>삼성전자주식회사</applicantName>
                    <applicationDate>20250115</applicationDate>
                    <registerStatus>등록</registerStatus>
                    <ipcNumber>G06F 16/33</ipcNumber>
                    <astrtCont>본 발명은 벡터 임베딩과 희소 검색을 결합하여 특허 문서를 고속 검색하는 시스템에 관한 것임.</astrtCont>
                </item>
            </items>
        </body>
    </response>"""

    class FakeResponse:
        def raise_for_status(self):
            return None

        @property
        def text(self):
            return xml_sample

        def json(self):
            raise ValueError("Not JSON")

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

        async def get(self, url, params=None):
            return FakeResponse()

    monkeypatch.setattr(kipris.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    res = run_async(kipris.search_patents(applicant="삼성전자", keyword="언어 모델"))
    assert res["success"] is True
    assert len(res["items"]) == 1
    assert res["items"][0]["application_number"] == "1020250012345"
    assert "지능형 특허 문서 검색" in res["items"][0]["title"]
    assert res["items"][0]["status"] == "등록"


def test_get_patent_detail_success(monkeypatch):
    """출원번호로 특허 상세 조회가 정상 수행되는지 검증함"""
    xml_sample = """<?xml version="1.0" encoding="UTF-8"?>
    <response>
        <body>
            <items>
                <item>
                    <applicationNumber>1020250012345</applicationNumber>
                    <inventionTitle>대규모 언어 모델 기반의 지능형 특허 문서 검색 시스템</inventionTitle>
                    <applicantName>삼성전자주식회사</applicantName>
                    <applicationDate>20250115</applicationDate>
                    <registerStatus>등록</registerStatus>
                    <ipcNumber>G06F 16/33</ipcNumber>
                    <astrtCont>본 발명은 고속 검색을 제공함.</astrtCont>
                </item>
            </items>
        </body>
    </response>"""

    class FakeResponse:
        def raise_for_status(self):
            return None

        @property
        def text(self):
            return xml_sample

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

        async def get(self, url, params=None):
            return FakeResponse()

    monkeypatch.setattr(kipris.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    detail = run_async(kipris.get_patent_detail(application_number="10-2025-0012345"))
    assert detail["success"] is True
    assert detail["application_number"] == "1020250012345"
    assert detail["legal_status"] == "등록"
    assert "고속 검색" in detail["abstract"]


def test_get_ipc_sections_resource():
    """국제특허분류 자원(Resource)이 정상 제공되는지 검증함"""
    doc = kipris.get_ipc_sections()
    assert "국제특허분류(IPC) 8대 표준 섹션" in doc
    assert "G" in doc
    assert "H" in doc


def test_analyze_patent_competitiveness_prompt():
    """특허 경쟁력 분석 프롬프트가 필수 지침을 포함하는지 검증함"""
    prompt = kipris.analyze_patent_competitiveness(
        company_name="현대자동차",
        target_technology="자율주행 라이다 센서",
    )
    assert "현대자동차" in prompt
    assert "자율주행 라이다 센서" in prompt
    assert "search_patents" in prompt
    assert "우수조달물품" in prompt
