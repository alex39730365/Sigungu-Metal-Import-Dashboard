# -*- coding: utf-8 -*-
"""
d1_client.py

Cloudflare D1(서버리스 SQLite) 데이터베이스를 REST(HTTP) API로 조작하는 얇은
클라이언트. 백엔드가 Render(Python/FastAPI)에서 실행되고 Cloudflare Worker에
바인딩되어 있지 않으므로, Cloudflare의 D1 HTTP API
(https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query)
를 통해 외부에서 직접 SQL을 실행한다.

필요 환경변수
-------------
CLOUDFLARE_ACCOUNT_ID   : Cloudflare 계정 ID
CLOUDFLARE_D1_DATABASE_ID : D1 데이터베이스 ID (wrangler d1 create 결과)
CLOUDFLARE_API_TOKEN   : D1 편집 권한이 있는 API 토큰

셋 중 하나라도 없으면 `is_configured()`가 False를 반환하며, 이를 호출하는
쪽(main.py)에서 D1 동기화를 건너뛰고 경고 로그만 남기도록 처리한다
(D1 미설정 상태에서도 기존 서비스는 정상 동작해야 한다).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

logger = logging.getLogger(__name__)

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"
DEFAULT_UPSERT_CHUNK_SIZE = 300  # 요청 1건당 UPSERT할 행 수 (D1 payload 제한 고려)


class D1ConfigError(RuntimeError):
    """D1 접속 정보가 설정되지 않았을 때 발생."""


class D1Client:
    def __init__(
        self,
        account_id: Optional[str] = None,
        database_id: Optional[str] = None,
        api_token: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.account_id = account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        self.database_id = database_id or os.environ.get("CLOUDFLARE_D1_DATABASE_ID")
        self.api_token = api_token or os.environ.get("CLOUDFLARE_API_TOKEN")
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.account_id and self.database_id and self.api_token)

    def _endpoint(self) -> str:
        return (
            f"{CLOUDFLARE_API_BASE}/accounts/{self.account_id}"
            f"/d1/database/{self.database_id}/query"
        )

    def query(self, sql: str, params: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
        """단일 SQL 문을 실행하고 D1 응답(JSON)을 반환한다.

        실패 시 RuntimeError를 발생시킨다 (호출부에서 try/except로 처리).
        """
        if not self.is_configured():
            raise D1ConfigError(
                "CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_D1_DATABASE_ID / "
                "CLOUDFLARE_API_TOKEN 환경변수가 설정되지 않았습니다."
            )

        resp = requests.post(
            self._endpoint(),
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
            json={"sql": sql, "params": list(params) if params else []},
            timeout=self.timeout,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"D1 응답 파싱 실패 (status={resp.status_code}): {resp.text[:500]}") from exc

        if not resp.ok or not payload.get("success", False):
            errors = payload.get("errors") or payload.get("result") or payload
            raise RuntimeError(f"D1 쿼리 실패 (status={resp.status_code}): {errors}")

        return payload

    def execute_schema(self, schema_sql: str) -> None:
        """schema.sql 내용을 실행한다. 여러 statement가 ';'로 구분되어 있으면
        하나씩 순서대로 실행한다 (D1 HTTP API는 한 요청당 단일 statement 권장)."""
        statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
        for stmt in statements:
            self.query(stmt)

    def upsert_rows(
        self,
        table: str,
        columns: Sequence[str],
        conflict_columns: Sequence[str],
        update_columns: Sequence[str],
        rows: Iterable[Sequence[Any]],
        chunk_size: int = DEFAULT_UPSERT_CHUNK_SIZE,
    ) -> int:
        """rows를 chunk_size 단위로 나누어
        `INSERT INTO table (...) VALUES (...), (...) ON CONFLICT(...) DO UPDATE SET ...`
        형태의 UPSERT 문을 실행한다. 반환값은 처리된 총 행 수.
        """
        rows = list(rows)
        if not rows:
            return 0

        col_list = ", ".join(columns)
        conflict_list = ", ".join(conflict_columns)
        update_clause = ", ".join(f"{c} = excluded.{c}" for c in update_columns)

        total = 0
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start : start + chunk_size]
            placeholders = ", ".join(
                "(" + ", ".join(["?"] * len(columns)) + ")" for _ in chunk
            )
            sql = (
                f"INSERT INTO {table} ({col_list}) VALUES {placeholders} "
                f"ON CONFLICT({conflict_list}) DO UPDATE SET {update_clause}"
            )
            flat_params: List[Any] = [v for row in chunk for v in row]
            self.query(sql, flat_params)
            total += len(chunk)

        return total


def get_d1_client() -> D1Client:
    return D1Client()
