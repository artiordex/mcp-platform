from __future__ import annotations

import asyncio

import pytest
import httpx

from mcp_platform.core import common
from mcp_platform.servers import food_safety, fsc, nps, nts, pps, portal_catalog


def run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture(autouse=True)
def configured_test_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")


def test_nps_normalizes_service_response(monkeypatch):
    async def fake_get_json(*args, **kwargs):
        return {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": {
                    "pageNo": 1,
                    "numOfRows": 100,
                    "totalCount": 1,
                    "items": {"item": {"seq": "7", "wkplNm": "테스트 사업장"}},
                },
            }
        }

    monkeypatch.setattr(nps, "get_json", fake_get_json)
    result = run(nps.search_business(wkpl_nm="테스트"))
    assert result["total_count"] == 1
    assert result["items"][0]["seq"] == "7"
    assert result["items"][0]["wkpl_nm"] == "테스트 사업장"


def test_pps_date_and_business_type_helpers():
    assert pps.format_datetime_for_api("2026-01-02") == "202601020000"
    assert pps.format_datetime_for_api("20260102", end=True) == "202601022359"
    assert pps.parse_business_type("용역") == "5"


def test_nts_formats_status_response(monkeypatch):
    async def fake_post(endpoint, body):
        assert endpoint == "status"
        assert body == {"b_no": ["1234567890"]}
        return {
            "request_cnt": 1,
            "match_cnt": 1,
            "data": [{"b_no": "1234567890", "b_stt": "계속사업자", "b_stt_cd": "01"}],
        }

    monkeypatch.setattr(nts, "_post", fake_post)
    result = run(nts.check_business_status("123-456-7890"))
    assert result["match_count"] == 1
    assert result["businesses"][0]["status"] == "계속사업자"


def test_fsc_financial_response_is_rendered(monkeypatch):
    async def fake_get_json(*args, **kwargs):
        return {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": {
                    "totalCount": 1,
                    "items": {
                        "item": {
                            "crno": "1234567890123",
                            "bizYear": "2024",
                            "enpSaleAmt": "100000000",
                            "curCd": "KRW",
                        }
                    },
                },
            }
        }

    monkeypatch.setattr(fsc, "get_json", fake_get_json)
    result = run(fsc.get_summary_financial_statement(crno="1234567890123", biz_year="2024"))
    assert "요약 재무제표" in result
    assert "1.00억" in result


def test_public_catalog_search_normalizes_response(monkeypatch):
    async def fake_post_json(*args, **kwargs):
        assert kwargs["json_body"]["keyword"] == "식품"
        return {
            "statusCode": 200,
            "result": [
                {
                    "sum": 1,
                    "dataCount": 1,
                    "data": [
                        {
                            "dataName": "식품 데이터",
                            "organization": "식품의약품안전처",
                            "firstBrmName": "보건",
                            "dataType": "API",
                            "detailPageUrl": "https://www.data.go.kr/data/1",
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(portal_catalog, "post_json", fake_post_json)
    result = run(portal_catalog.search_public_datasets(keyword="식품"))
    assert result["total_count"] == 1
    assert result["items"][0]["name"] == "식품 데이터"
    assert result["items"][0]["categories"] == ["보건"]


def test_food_safety_response_normalizes_service_envelope(monkeypatch):
    async def fake_get_json(url):
        assert "/I1250/json/1/20/" in url
        assert "PRDLST_NM=%EA%B9%80%EC%B9%98" in url
        return {
            "I1250": {
                "total_count": "1",
                "row": [{"PRDLST_NM": "김치", "BSSH_NM": "테스트 제조사"}],
                "RESULT": {"CODE": "INFO-000", "MSG": "정상 처리되었습니다."},
            }
        }

    monkeypatch.setenv("FOOD_SAFETY_API_KEY", "food-test-key")
    monkeypatch.setattr(food_safety, "get_json", fake_get_json)
    result = run(
        food_safety.search_food_manufacturing_reports(
            product_name="김치",
            num_of_rows=20,
        )
    )
    assert result["total_count"] == 1
    assert result["items"][0]["PRDLST_NM"] == "김치"


def test_service_key_prefers_data_go_key_over_legacy_alias(monkeypatch):
    monkeypatch.setenv("DATA_GO_API_KEY", "preferred-data-key")
    monkeypatch.setenv("API_KEY", "legacy-key")
    assert common.service_key() == "preferred-data-key"


def test_provider_error_message_redacts_configured_api_key(monkeypatch):
    secret = "food-secret-key"
    monkeypatch.setenv("FOOD_SAFETY_API_KEY", secret)

    with pytest.raises(common.DataGoError) as error:
        common.response_body(
            {
                "response": {
                    "header": {
                        "resultCode": "99",
                        "resultMsg": f"request rejected for {secret}",
                    },
                    "body": {},
                }
            }
        )

    assert secret not in str(error.value)
    assert "[REDACTED]" in str(error.value)


def test_http_status_error_does_not_expose_url_or_response_body(monkeypatch):
    secret = "service-key-in-path"
    url = f"https://api.example.test/{secret}/json"
    monkeypatch.setenv("FOOD_SAFETY_API_KEY", secret)

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, request_url, **kwargs):
            response = httpx.Response(
                403,
                text=f"provider echoed {secret}",
                request=httpx.Request("GET", request_url),
            )
            return response

    monkeypatch.setattr(common.httpx, "AsyncClient", lambda **kwargs: FailingClient())

    with pytest.raises(common.DataGoError) as error:
        run(common.get_json(url))

    message = str(error.value)
    assert "403" in message
    assert secret not in message
    assert "api.example.test" not in message
    assert "provider echoed" not in message
