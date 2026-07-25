# -*- coding: utf-8 -*-
"""
DART OpenAPI 를 실시간으로 검색하여 시군구별 금속 관련 기업을 반환하는 모듈.

사용 방식:
    export DART_API_KEY=<키>
    # main.py 에서 DartSearcher 인스턴스로 호출

주의:
    DART OpenAPI 는 지역/업종 기반 검색 엔드포인트를 제공하지 않으므로,
    `corpCode.xml` (1회 다운로드, 약 11,000개 기업 목록) 을 받은 뒤
    금속 관련 키워드로 기업명을 필터링하고, 해당 후보 기업들에 대해서만
    `company.json` 을 호출하여 주소와 업종코드를 확인합니다.
"""
from __future__ import annotations

import io
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
COMPANY_URL = "https://opendart.fss.or.kr/api/company.json"

# 기업명에 다음 키워드가 포함되면 금속 관련 후보로 간주
DEFAULT_METAL_KEYWORDS = (
    "철강",
    "제철",
    "제강",
    "금속",
    "비철",
    "스틸",
    "철관",
    "알루미늄",
    "구리",
    "아연",
    "니켈",
    "코발트",
    "리튬",
    "마그네슘",
    "티타늄",
    "희유",
    "주석",
    "납",
    "주조",
    "단조",
    "도금",
    "합금",
    "포스코",
    "현대제철",
    "동국제강",
    "세아",
    "고려아연",
    "영풍",
    "LS",
    "KG",
    "한국철강",
    "금강",
)

# 업종코드가 다음 접두어로 시작하면 금속 관련으로 간주
# KSIC 10차: 23=1차 금속 제조업, 24=금속가공제품 제조업, 4672=금속광물 도매
METAL_INDUSTRY_PREFIXES = ("23", "24", "4672")

# 시도 명칭 정규화
SIDO_NAME_MAP = {
    "강원": "강원특별자치도",
    "강원도": "강원특별자치도",
    "전라북도": "전북특별자치도",
    "전북": "전북특별자치도",
    "전라남도": "전라남도",
    "경상북도": "경상북도",
    "경상남도": "경상남도",
    "충청북도": "충청북도",
    "충청남도": "충청남도",
    "경기": "경기도",
    "경기도": "경기도",
    "제주": "제주특별자치도",
    "제주도": "제주특별자치도",
    "세종": "세종특별자치시",
    "세종시": "세종특별자치시",
}


def _normalize_sido(token: str) -> str:
    return SIDO_NAME_MAP.get(token, token)


def _extract_sigungu(address: str) -> Optional[str]:
    """DART 기업 주소에서 '시도명 시군구명' 형태로 추출."""
    if not address:
        return None

    cleaned = re.sub(r"\([^)]*\)", "", address)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if cleaned.startswith("세종"):
        return "세종특별자치시"

    sido_pattern = (
        r"(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|"
        r"대전광역시|울산광역시|세종특별자치시|세종시|제주특별자치도|제주도|"
        r"강원특별자치도|강원도|경기도|경상북도|경상남도|전라남도|"
        r"전북특별자치도|전라북도|전북|충청북도|충청남도)"
    )
    pattern = re.compile(rf"{sido_pattern}\s+([^\s]+(?:시|군|구))")
    match = pattern.search(cleaned)
    if not match:
        return None

    sido = _normalize_sido(match.group(1))
    sigungu = match.group(2)
    return f"{sido} {sigungu}"


def _is_metal_related(name: str, induty_code: Optional[str]) -> bool:
    """기업명 또는 업종코드가 금속 관련이면 True."""
    lower_name = name.lower()
    if any(k in lower_name for k in DEFAULT_METAL_KEYWORDS):
        return True
    if induty_code:
        if induty_code.startswith(METAL_INDUSTRY_PREFIXES):
            return True
    return False


class DartSearcher:
    def __init__(self, api_key: str):
        if not api_key:
            raise RuntimeError("DART_API_KEY 환경변수가 설정되어 있지 않습니다.")
        self.api_key = api_key
        self.session = self._create_session()
        self._corp_codes: List[Dict[str, str]] = []
        self._corp_codes_fetched_at: Optional[datetime] = None
        self._corp_cache_ttl = timedelta(hours=24)
        # (region, keyword) -> (fetched_at, results)
        self._result_cache: Dict[tuple, tuple] = {}
        self._result_cache_ttl = timedelta(hours=1)

    @staticmethod
    def _create_session() -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, application/xml, */*",
        })
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=8, pool_maxsize=16)
        session.mount("https://", adapter)
        return session

    def _fetch_corp_codes(self) -> List[Dict[str, str]]:
        """DART 고유번호 목록을 다운로드/파싱 (zip+xml)."""
        resp = self.session.get(
            CORP_CODE_URL, params={"crtfc_key": self.api_key}, timeout=120
        )
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            xml_name = next(
                (n for n in z.namelist() if n.lower().endswith(".xml")), None
            )
            if not xml_name:
                raise RuntimeError("CORPCODE xml 파일을 찾을 수 없습니다.")
            with z.open(xml_name) as xml_file:
                tree = ET.parse(xml_file)

        root = tree.getroot()
        corps = []
        for node in root.findall("list"):
            corp_code = (node.findtext("corp_code") or "").strip()
            corp_name = (node.findtext("corp_name") or "").strip()
            stock_code = (node.findtext("stock_code") or "").strip()
            if not corp_code:
                continue
            corps.append(
                {"corp_code": corp_code, "corp_name": corp_name, "stock_code": stock_code}
            )

        self._corp_codes = corps
        self._corp_codes_fetched_at = datetime.now()
        return corps

    def get_corp_codes(self) -> List[Dict[str, str]]:
        """캐시된 고유번호 목록 반환 (TTL 24시간)."""
        if self._corp_codes and self._corp_codes_fetched_at:
            if datetime.now() - self._corp_codes_fetched_at < self._corp_cache_ttl:
                return self._corp_codes
        return self._fetch_corp_codes()

    def _fetch_company(self, corp: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """개별 기업의 기업개황 조회."""
        try:
            resp = self.session.get(
                COMPANY_URL,
                params={"crtfc_key": self.api_key, "corp_code": corp["corp_code"]},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None

        if "adres" not in data:
            return None

        return {
            "corp_code": data.get("corp_code") or corp["corp_code"],
            "corp_name": data.get("corp_name") or corp["corp_name"],
            "stock_code": data.get("stock_code") or corp.get("stock_code", ""),
            "adres": data.get("adres", ""),
            "induty_code": data.get("induty_code", ""),
        }

    def search(
        self,
        region_name: str,
        keyword: Optional[str] = None,
        limit: int = 50,
        max_candidates: int = 120,
    ) -> List[Dict[str, Any]]:
        """지역 + 키워드로 금속 관련 DART 기업을 실시간 검색."""
        cache_key = (region_name.strip(), (keyword or "").strip())
        cached = self._result_cache.get(cache_key)
        if cached:
            fetched_at, results = cached
            if datetime.now() - fetched_at < self._result_cache_ttl:
                return results

        corps = self.get_corp_codes()
        region_key = region_name.strip()

        if keyword and keyword.strip():
            kw = keyword.strip().lower()
            candidates = [c for c in corps if kw in c["corp_name"].lower()]
        else:
            candidates = [
                c
                for c in corps
                if any(k in c["corp_name"].lower() for k in DEFAULT_METAL_KEYWORDS)
            ]

        candidates = candidates[:max_candidates]
        results: List[Dict[str, Any]] = []

        start_time = time.time()
        max_runtime = 40  # 초
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_corp = {
                executor.submit(self._fetch_company, c): c for c in candidates
            }
            for future in as_completed(future_to_corp):
                if time.time() - start_time > max_runtime:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                info = future.result()
                if not info:
                    continue
                sigungu = _extract_sigungu(info.get("adres", ""))
                if not sigungu or sigungu != region_key:
                    continue
                if _is_metal_related(info.get("corp_name", ""), info.get("induty_code")):
                    results.append(info)

        results.sort(key=lambda x: x["corp_name"])
        results = results[:limit]
        self._result_cache[cache_key] = (datetime.now(), results)
        return results

    def clear_cache(self) -> None:
        self._corp_codes = []
        self._corp_codes_fetched_at = None
        self._result_cache.clear()


def create_dart_searcher() -> Optional[DartSearcher]:
    api_key = __import__("os").environ.get("DART_API_KEY")
    if not api_key:
        return None
    return DartSearcher(api_key)


if __name__ == "__main__":
    import os

    key = os.environ.get("DART_API_KEY")
    if not key:
        print("DART_API_KEY 환경변수를 설정해주세요.")
    else:
        ds = DartSearcher(key)
        print("기업 수:", len(ds.get_corp_codes()))
        print("울산 울주군:", ds.search("울산광역시 울주군"))
