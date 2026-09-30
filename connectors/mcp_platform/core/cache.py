# =============================================================================
# 파일명: cache.py
# 경로: connectors/mcp_platform/core/cache.py
# 목적: 외부 API 호출 결과의 메모리 기반 TTL 캐싱 및 쿼터 절약을 담당함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""외부 API 호출 결과의 메모리 기반 TTL 캐싱 및 쿼터 절약을 담당함"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any


class TTLCache:
    """만료 시간(TTL) 기반 인메모리 캐시 저장소임"""

    def __init__(self, default_ttl_seconds: int = 300, max_entries: int = 1000):
        """캐시 인스턴스를 초기화함

        Args:
            default_ttl_seconds: 기본 유효 시간(초 단위, 기본 5분)임
            max_entries: 최대 보관 항목 수임
        """
        self._default_ttl = default_ttl_seconds
        self._max_entries = max_entries
        self._store: dict[str, tuple[float, Any]] = {}

    def _cleanup_expired(self) -> None:
        """만료된 항목을 정리함"""
        now = time.monotonic()
        expired_keys = [k for k, (exp, _) in self._store.items() if now >= exp]
        for key in expired_keys:
            self._store.pop(key, None)

    def get(self, key: str) -> Any | None:
        """키에 해당하는 유효한 캐시 값을 조회함

        Args:
            key: 캐시 식별자 키임

        Returns:
            유효한 캐시 데이터 또는 None임
        """
        item = self._store.get(key)
        if item is None:
            return None
        expire_at, value = item
        if time.monotonic() >= expire_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """캐시 데이터를 저장함

        Args:
            key: 캐시 식별자 키임
            value: 저장할 데이터 객체임
            ttl_seconds: 개별 유효 시간임 (생략 시 기본값 사용함)
        """
        if len(self._store) >= self._max_entries:
            self._cleanup_expired()
            if len(self._store) >= self._max_entries:
                keys_to_remove = list(self._store.keys())[: self._max_entries // 5]
                for k in keys_to_remove:
                    self._store.pop(k, None)

        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        self._store[key] = (time.monotonic() + ttl, value)

    def make_key(self, prefix: str, **kwargs: Any) -> str:
        """요청 파라미터를 해시하여 고유 캐시 키를 생성함

        Args:
            prefix: 도메인 또는 엔드포인트 접두사임
            kwargs: 요청 인자 매핑임

        Returns:
            SHA256 해시 기반의 고유 식별자 문자열임
        """
        serialized = json.dumps(kwargs, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        return f"{prefix}:{digest}"


# 전역 기본 TTL 캐시 인스턴스 (기본 TTL: 10분, 최대 2000건)
api_cache = TTLCache(default_ttl_seconds=600, max_entries=2000)
