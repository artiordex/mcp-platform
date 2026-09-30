# =============================================================================
# 파일명: cache.py
# 경로: connectors/mcp_platform/core/cache.py
# 목적: 메모리(L1) 및 SQLite(L2) 계층형 캐시를 통해 외부 API 쿼터를 절약하고 응답 속도를 최적화함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""메모리(L1) 및 SQLite(L2) 계층형 캐시를 통해 외부 API 쿼터를 절약하고 응답 속도를 최적화함"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


class TTLCache:
    """만료 시간(TTL) 기반 인메모리 L1 캐시 저장소임"""

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
            value: 저장할 임의 데이터임
            ttl_seconds: 개별 유효 시간임 (미지정 시 기본값 적용함)
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expire_at = time.monotonic() + max(ttl, 1)

        if len(self._store) >= self._max_entries:
            self._cleanup_expired()
            if len(self._store) >= self._max_entries:
                oldest_key = next(iter(self._store))
                self._store.pop(oldest_key, None)

        self._store[key] = (expire_at, value)

    def clear(self) -> None:
        """메모리 캐시를 초기화함"""
        self._store.clear()

    @property
    def size(self) -> int:
        """보관 중인 항목 수임"""
        return len(self._store)

    @staticmethod
    def make_key(namespace: str, **kwargs: Any) -> str:
        """네임스페이스와 매개변수 집합으로 결정론적 고유 해시 키를 생성함

        Args:
            namespace: 도구 또는 서비스 식별자임
            kwargs: 요청 파라미터 키-값 쌍임

        Returns:
            SHA-256 기반 16진수 문자열 키임
        """
        sorted_pairs = sorted((k, str(v)) for k, v in kwargs.items() if v is not None)
        raw = f"{namespace}:" + json.dumps(sorted_pairs, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SQLiteCache:
    """SQLite 기반 L2 디스크 영속 캐시 저장소임"""

    def __init__(self, db_path: str | Path | None = None, default_ttl_seconds: int = 3600):
        """SQLite 캐시 테이블을 생성하고 초기화함"""
        if db_path is None:
            root_dir = Path(__file__).resolve().parents[3]
            runtime_dir = root_dir / ".runtime"
            runtime_dir.mkdir(exist_ok=True)
            self._db_path = str(runtime_dir / "mcp_cache.db")
        else:
            self._db_path = str(db_path)
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._default_ttl = default_ttl_seconds
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """SQLite 데이터베이스 연결을 생성함"""
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        """캐시 테이블 스키마를 초기화함"""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expire_at REAL NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_expire ON cache_entries(expire_at)")

    def get(self, key: str) -> Any | None:
        """디스크 캐시에서 유효한 데이터를 조회함"""
        now = time.time()
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value, expire_at FROM cache_entries WHERE key = ?", (key,))
            row = cur.fetchone()
            if not row:
                return None
            val_text, expire_at = row
            if now >= expire_at:
                conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                return None
            try:
                return json.loads(val_text)
            except Exception:
                return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """디스크 캐시에 데이터를 직렬화하여 저장함"""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        now = time.time()
        expire_at = now + max(ttl, 1)
        try:
            val_text = json.dumps(value, ensure_ascii=False)
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO cache_entries (key, value, expire_at, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (key, val_text, expire_at, now),
                )
        except Exception:
            pass

    def clear(self) -> None:
        """디스크 캐시 데이터를 전량 삭제함"""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM cache_entries")

    def count(self) -> int:
        """유효한 디스크 캐시 레코드 수를 반환함"""
        now = time.time()
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM cache_entries WHERE expire_at > ?", (now,))
            row = cur.fetchone()
            return row[0] if row else 0


class TieredCache:
    """L1(메모리)과 L2(SQLite)를 결합한 고성능 2계층 캐시 관리자임"""

    def __init__(self, l1: TTLCache, l2: SQLiteCache):
        self._l1 = l1
        self._l2 = l2

    def get(self, key: str) -> Any | None:
        """L1 메모리 조회 후 미적중 시 L2 디스크 캐시에서 승격 조회함"""
        val = self._l1.get(key)
        if val is not None:
            return val

        val = self._l2.get(key)
        if val is not None:
            self._l1.set(key, val, ttl_seconds=300)
            return val
        return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """L1 메모리와 L2 디스크에 동시 저장함"""
        self._l1.set(key, value, ttl_seconds=ttl_seconds)
        self._l2.set(key, value, ttl_seconds=ttl_seconds)

    def make_key(self, namespace: str, **kwargs: Any) -> str:
        """결정론적 해시 키를 생성함"""
        return TTLCache.make_key(namespace, **kwargs)

    def clear(self) -> None:
        """L1 및 L2 캐시를 모두 초기화함"""
        self._l1.clear()
        self._l2.clear()

    def stats(self) -> dict[str, Any]:
        """캐시 현황 통계를 반환함"""
        return {
            "l1_memory_entries": self._l1.size,
            "l2_disk_entries": self._l2.count(),
        }


# 글로벌 싱글톤 2계층 캐시 인스턴스
_l1_cache = TTLCache(default_ttl_seconds=300, max_entries=1000)
_l2_cache = SQLiteCache(default_ttl_seconds=3600)
api_cache = TieredCache(_l1_cache, _l2_cache)
