#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DART 금속 기업 인덱스를 로컬에서 사전 빌드하는 스크립트.

실행 방법:
    cd dashboard/backend
    set DART_API_KEY=<인증키>   # Windows PowerShell
    # 또는 Linux/macOS:
    export DART_API_KEY=<인증키>
    python build_dart_metal_index.py

결과:
    동일 폴더에 dart_metal_index.json 이 생성됩니다.
    이 파일을 Render/GitHub에 포함시켜 서버에서는 무거운 DART API 호출 없이 바로 로드합니다.
"""
import os
import sys

from dart_company_index import DartCompanyIndex


def main() -> int:
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        print("오류: DART_API_KEY 환경변수를 설정해주세요.")
        return 1

    index = DartCompanyIndex(api_key)
    print("DART 금속 기업 인덱스 빌드 시작...")
    try:
        ok = index.trigger_refresh()
        if not ok:
            print("오류: 인덱스 구축에 실패했습니다. 로그를 확인해주세요.")
            return 1
    except KeyboardInterrupt:
        print("\n사용자에 의해 중단되었습니다.")
        return 130

    count = len(index.companies)
    print(f"빌드 완료: {count} 건의 금속 기업이 저장되었습니다.")
    print(f"파일 위치: {index.cache_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
