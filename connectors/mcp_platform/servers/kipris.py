# =============================================================================
# 파일명: kipris.py
# 경로: connectors/mcp_platform/servers/kipris.py
# 목적: 특허청 KIPRIS 특허 및 실용신안 출원·등록 정보 조회를 제공함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""특허청 KIPRIS 특허 및 실용신안 출원·등록 정보 조회를 제공함"""

from __future__ import annotations

import os
from typing import Any
import xml.etree.ElementTree as ET

import httpx
from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import error_result

mcp = FastMCP("특허청 KIPRIS 특허 및 실용신안 정보 서비스")

KIPRIS_BASE_URL = os.getenv(
    "KIPRIS_BASE_URL",
    "http://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/getWordSearch",
)
KIPRIS_API_KEY = os.getenv("KIPRIS_API_KEY", os.getenv("DATA_GO_API_KEY", "dev_test_key"))

IPC_SECTIONS = {
    "A": "인간생활필수 (농업, 식품, 의류, 주거, 의학)",
    "B": "처리조작 및 운수 (분리, 혼합, 가공, 인쇄, 운반)",
    "C": "화학 및 야금 (유기화학, 무기화학, 유리, 시멘트)",
    "D": "섬유 및 지류 (천연/인조 섬유, 방적, 제지)",
    "E": "고정구조물 (건축, 토목, 채광)",
    "F": "기계공학, 조명, 가열, 무기, 폭파",
    "G": "물리학 (계측, 광학, 제어, 전자기기)",
    "H": "전기 (회로, 반도체, 통신, 발전)",
}


def _parse_xml_patents(xml_text: str) -> list[dict[str, Any]]:
    """KIPRIS XML 응답에서 특허 항목 목록을 추출함"""
    items = []
    try:
        root = ET.fromstring(xml_text)
        for node in root.findall(".//item"):
            app_num = node.findtext("applicationNumber", "")
            title = node.findtext("inventionTitle", "")
            applicant = node.findtext("applicantName", "")
            app_date = node.findtext("applicationDate", "")
            reg_status = node.findtext("registerStatus", "등록/공개")
            ipc_num = node.findtext("ipcNumber", "")
            astrt = node.findtext("astrtCont", "")

            items.append(
                {
                    "application_number": app_num.strip(),
                    "title": title.strip(),
                    "applicant": applicant.strip(),
                    "application_date": app_date.strip(),
                    "status": reg_status.strip(),
                    "ipc_code": ipc_num.strip(),
                    "abstract": astrt.strip(),
                }
            )
    except Exception:
        pass
    return items


@mcp.tool()
async def search_patents(
    applicant: str = "",
    keyword: str = "",
    page_no: int = 1,
    num_of_rows: int = 10,
) -> dict[str, Any]:
    """출원인(기업명) 또는 발명의 명칭 키워드로 특허 및 실용신안 등록 목록을 검색함

    Args:
        applicant: 특허 출원인 또는 권리자 기업명임 (예: 삼성전자, 현대자동차)
        keyword: 기술명, 발명의 명칭 키워드임 (예: 인공지능, 자율주행, 배터리)
        page_no: 조회할 페이지 번호임 (기본값: 1)
        num_of_rows: 반환할 특허 건수임 (기본 10건, 최대 50건)

    Returns:
        특허 목록(출원번호, 발명의 명칭, 출원일자, 권리상태, IPC 분류) 객체임
    """
    clean_applicant = applicant.strip()
    clean_keyword = keyword.strip()

    if not clean_applicant and not clean_keyword:
        return {"success": False, "error": "applicant 또는 keyword 중 최소 1개는 필수임", "items": []}

    cache_key = api_cache.make_key(
        "kipris_search",
        app=clean_applicant,
        kw=clean_keyword,
        p=page_no,
        rows=num_of_rows,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    # 검색 쿼리 구성
    query_parts = []
    if clean_keyword:
        query_parts.append(clean_keyword)
    if clean_applicant:
        query_parts.append(f"AP=[{clean_applicant}]")
    combined_query = " ".join(query_parts)

    params = {
        "word": combined_query,
        "accessKey": KIPRIS_API_KEY,
        "numOfRows": min(max(num_of_rows, 1), 50),
        "pageNo": page_no,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(KIPRIS_BASE_URL, params=params)
            resp.raise_for_status()
            text_body = resp.text

            # JSON 또는 XML 파싱 시도
            items = []
            total_count = 0
            if text_body.strip().startswith("{"):
                json_data = resp.json()
                body_elem = json_data.get("response", {}).get("body", {})
                total_count = body_elem.get("totalCount", 0)
                raw_items = body_elem.get("items", {}).get("item", [])
                if isinstance(raw_items, dict):
                    raw_items = [raw_items]
                for it in raw_items:
                    items.append(
                        {
                            "application_number": it.get("applicationNumber", ""),
                            "title": it.get("inventionTitle", ""),
                            "applicant": it.get("applicantName", clean_applicant),
                            "application_date": it.get("applicationDate", ""),
                            "status": it.get("registerStatus", "등록"),
                            "ipc_code": it.get("ipcNumber", ""),
                            "abstract": it.get("astrtCont", ""),
                        }
                    )
            else:
                items = _parse_xml_patents(text_body)
                total_count = len(items)

            result = {
                "success": True,
                "total_count": total_count,
                "page_no": page_no,
                "applicant": clean_applicant,
                "keyword": clean_keyword,
                "items": items,
            }
            api_cache.set(cache_key, result, ttl_seconds=3600)
            return result

    except httpx.HTTPError as exc:
        return error_result(
            operation="kipris.search_patents",
            service_name="특허청 KIPRIS 오픈API",
            target_id=combined_query,
            cause=exc,
        )
    except Exception as exc:
        return {
            "success": False,
            "error": f"특허 검색 중 오류 발생함: {exc}",
            "items": [],
        }


@mcp.tool()
async def get_patent_detail(
    application_number: str,
) -> dict[str, Any]:
    """출원번호(application_number)로 특허의 발명 요약, 대표 청구항 및 행정 상태를 조회함

    Args:
        application_number: 특허 출원번호임 (예: 1020230123456)

    Returns:
        상세 발명의 요약(초록), 출원인, 권리자, 법적 상태 정보 객체임
    """
    clean_num = application_number.strip().replace("-", "")
    if not clean_num:
        return {"success": False, "error": "application_number 매개변수가 필수임"}

    cache_key = api_cache.make_key("kipris_detail", app_no=clean_num)
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    params = {
        "word": f"AN=[{clean_num}]",
        "accessKey": KIPRIS_API_KEY,
        "numOfRows": 1,
        "pageNo": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(KIPRIS_BASE_URL, params=params)
            resp.raise_for_status()
            text_body = resp.text

            items = []
            if text_body.strip().startswith("{"):
                json_data = resp.json()
                raw_items = json_data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
                if isinstance(raw_items, dict):
                    raw_items = [raw_items]
                for it in raw_items:
                    items.append(
                        {
                            "application_number": it.get("applicationNumber", clean_num),
                            "title": it.get("inventionTitle", ""),
                            "applicant": it.get("applicantName", ""),
                            "application_date": it.get("applicationDate", ""),
                            "status": it.get("registerStatus", "등록"),
                            "ipc_code": it.get("ipcNumber", ""),
                            "abstract": it.get("astrtCont", ""),
                        }
                    )
            else:
                items = _parse_xml_patents(text_body)

            if not items:
                return {
                    "success": False,
                    "error": f"출원번호 {clean_num}에 해당하는 특허 상세를 찾을 수 없음",
                }

            detail = items[0]
            result = {
                "success": True,
                "application_number": clean_num,
                "title": detail["title"],
                "applicant": detail["applicant"],
                "application_date": detail["application_date"],
                "legal_status": detail["status"],
                "ipc_code": detail["ipc_code"],
                "abstract": detail["abstract"],
            }
            api_cache.set(cache_key, result, ttl_seconds=86400)
            return result

    except httpx.HTTPError as exc:
        return error_result(
            operation="kipris.get_patent_detail",
            service_name="특허청 KIPRIS 오픈API",
            target_id=clean_num,
            cause=exc,
        )
    except Exception as exc:
        return {"success": False, "error": f"특허 상세 조회 중 오류 발생함: {exc}"}


@mcp.resource("kipris://ipc-sections")
def get_ipc_sections() -> str:
    """국제특허분류(IPC) 8대 표준 섹션 명세를 반환함"""
    lines = ["# 국제특허분류(IPC) 8대 표준 섹션 체계", ""]
    for code, desc in IPC_SECTIONS.items():
        lines.append(f"- **섹션 {code}**: {desc}")
    lines.append("")
    lines.append("## 기술 권리 진단 기준")
    lines.append("- G섹션(물리학) 및 H섹션(전기/전자) 집중 기업: ICT/AI 소프트웨어 및 반도체 핵심 기술군")
    lines.append("- C섹션(화학) 및 A섹션(바이오/의학) 집중 기업: 소재·부품·장비 및 바이오헬스 기술군")
    return "\n".join(lines)


@mcp.prompt()
def analyze_patent_competitiveness(
    company_name: str,
    target_technology: str,
) -> str:
    """기업의 특허 포트폴리오를 기반으로 기술적 진입장벽과 분쟁 가능성을 진단하는 프롬프트임"""
    return (
        f"당신은 공공 지식재산권(IP) 및 기술가치 평가 수석 변리사입니다.\n\n"
        f"진단 대상 기업: {company_name}\n"
        f"주요 분석 기술 분야: {target_technology}\n\n"
        f"작업 지침:\n"
        f"1. 먼저 `search_patents` 도구를 사용하여 {company_name}의 최근 등록 특허 및 출원 동향을 조회하세요.\n"
        f"2. 핵심 보유 특허의 IPC 분류와 기술 요약(초록)을 검토하여 해당 분야의 독점적 기술 장벽 구축 여부를 판정하세요.\n"
        f"3. 특허 소멸, 거절, 취하 여부 등 행정 상태를 점검하여 기술 권리의 안정성을 평가하세요.\n"
        f"4. 조달청 나라장터 우수조달물품 지정 또는 R&D 과제 수주 시 특허 가점 취득 적합성을 3가지 항목으로 제안하세요."
    )
