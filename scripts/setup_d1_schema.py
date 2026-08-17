# -*- coding: utf-8 -*-
"""
scripts/setup_d1_schema.py

Cloudflare D1의 `monthly_metal_stats` 테이블을 (재)생성하는 1회성 스크립트.

주의
----
d1/schema.sql은 `DROP TABLE IF EXISTS monthly_metal_stats`로 시작하므로,
이 스크립트를 실행하면 기존에 D1에 쌓여있던 데이터가 모두 삭제된다.
서버 코드(dashboard/backend/main.py)의 자동 갱신 흐름에서는 절대
이 스크립트/스키마를 호출하지 않으며, 최초 설정 또는 스키마 변경 시에만
사람이 직접 실행해야 한다.

사용법
------
1. 환경변수 설정:
   CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_D1_DATABASE_ID, CLOUDFLARE_API_TOKEN
2. 실행:
   python scripts/setup_d1_schema.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard" / "backend"))

from d1_client import get_d1_client  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "d1" / "schema.sql"


def main() -> None:
    client = get_d1_client()
    if not client.is_configured():
        print(
            "CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_D1_DATABASE_ID / CLOUDFLARE_API_TOKEN "
            "환경변수를 먼저 설정하세요."
        )
        sys.exit(1)

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    confirm = os.environ.get("CONFIRM_DROP") == "yes"
    if not confirm:
        answer = input(
            "monthly_metal_stats 테이블이 존재하면 삭제 후 재생성합니다. 계속하시겠습니까? (yes/no): "
        )
        if answer.strip().lower() != "yes":
            print("취소되었습니다.")
            return

    client.execute_schema(schema_sql)
    print("D1 스키마 적용 완료: monthly_metal_stats 테이블 생성됨.")


if __name__ == "__main__":
    main()
