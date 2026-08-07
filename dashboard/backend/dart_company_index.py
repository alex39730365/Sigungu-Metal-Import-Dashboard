# -*- coding: utf-8 -*-
"""
DART OpenAPI 기반 금속 관련 기업 인덱스 모듈.

[설계 목표]
- 서버 구동 시(또는 주기적 갱신 시) DART 고유번호 파일(corpCode.xml)을 1회 다운로드
- 전체 기업의 기업개황(company.json)을 수집하여 메탈 키워드/업종코드로 1차 필터링
- 필터링된 금속 기업 리스트를 메모리 + JSON 캐시에 저장
- 사용자 검색 시 외부 API 호출 없이 내부 인덱스에서 즉시 검색
- 상세정보/재무정보 요청 시에만 DART API 를 실시간 호출

사용 예:
    index = DartCompanyIndex(api_key=os.environ["DART_API_KEY"])
    index.start_background_refresh()          # 백그라운드에서 인덱스 구축/갱신
    companies = index.search_by_region("울산광역시 울주군", keyword="철강")
    detail = index.get_company_detail(company["corp_code"])
    finance = index.get_financial_statements(company["corp_code"], "2025", "11011")
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
COMPANY_URL = "https://opendart.fss.or.kr/api/company.json"
FINANCIAL_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

# 금속 관련 기업명 키워드
METAL_KEYWORDS: tuple = (
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
    "신소재",
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

# KSIC 10차 기준 금속 관련 업종코드 접두어
# 23=1차 금속 제조업, 24=금속가공제품 제조업, 4672=금속광물 도매
METAL_INDUSTRY_PREFIXES: tuple = ("23", "24", "4672")

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


def extract_sigungu(address: str) -> Optional[str]:
    """주소에서 '시도명 시군구명' 형태를 추출합니다."""
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


def is_metal_name(name: str) -> bool:
    """기업명에 금속 관련 키워드가 포함되면 True."""
    return any(k in name.lower() for k in METAL_KEYWORDS)


def is_metal_related(name: str, induty_code: Optional[str]) -> bool:
    """기업명 또는 업종코드가 금속 관련이면 True."""
    if is_metal_name(name):
        return True
    if induty_code and induty_code.startswith(METAL_INDUSTRY_PREFIXES):
        return True
    return False


class DartCompanyIndex:
    """DART 금속 기업 인덱스: 전체 기업 중 금속 관련 기업만 사전 필터링 및 캐싱."""

    def __init__(
        self,
        api_key: str,
        cache_dir: Optional[Path] = None,
        max_workers: int = 2,
        refresh_interval_hours: int = 24,
        chunk_size: int = 10,
    ) -> None:
        if not api_key:
            raise RuntimeError("DART_API_KEY 는 필수입니다.")

        self.api_key = api_key
        self.cache_dir = cache_dir or Path(__file__).resolve().parent
        self.cache_path = self.cache_dir / "dart_metal_index.json"
        self.ksic_path = self.cache_dir / "ksic_10.json"
        self.ksic_map = self._load_ksic()
        self.max_workers = max_workers
        self.refresh_interval = timedelta(hours=refresh_interval_hours)
        self.chunk_size = chunk_size

        self.companies: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._loaded = False
        self._loading = False
        self._last_error: Optional[str] = None
        self._last_loaded_at: Optional[datetime] = None
        self._refresh_thread: Optional[threading.Thread] = None

        self.session = self._create_session()

        # 서버 구동 시 파일이 있으면 즉시 로드, 없으면 비어있는 상태로 둔다.
        self._load_from_file()

    def _load_ksic(self) -> Dict[str, str]:
        """KSIC 10차 코드표(ksic_10.json)를 메모리에 로드."""
        if not self.ksic_path.exists():
            return {}
        try:
            with open(self.ksic_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("KSIC 코드표 로드 실패: %s", e)
            return {}

    def _get_induty_name(self, code: str) -> str:
        """업종코드에 해당하는 KSIC 한글명 반환. 정확한 코드가 없으면 상위 코드로 fallback."""
        if not code:
            return ""
        c = code.strip()
        while c:
            name = self.ksic_map.get(c)
            if name:
                return name
            c = c[:-1]
        return ""

    def _load_from_file(self) -> bool:
        """dart_metal_index.json 파일을 TTL 관계없이 즉시 메모리에 로드."""
        if not self.cache_path.exists():
            logger.warning("DART 인덱스 파일이 없습니다: %s", self.cache_path)
            return False
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            companies = payload.get("companies", [])
            with self._lock:
                self.companies = companies
                self._loaded = bool(companies)
                self._last_loaded_at = datetime.fromtimestamp(
                    self.cache_path.stat().st_mtime
                )
                self._last_error = None
            logger.info("DART 인덱스 파일 로드 완료: %s 건", len(companies))
            return True
        except Exception as e:
            logger.error("DART 인덱스 파일 로드 실패: %s", e)
            return False

    @staticmethod
    def _create_session() -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, application/xml, text/html, */*;q=0.9",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        })
        retries = Retry(
            total=2,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(
            max_retries=retries,
            pool_connections=4,
            pool_maxsize=8,
        )
        session.mount("https://", adapter)
        return session

    # --------------------------------------------------------------------------
    # 캐시
    # --------------------------------------------------------------------------

    def _save_cache(self) -> None:
        """메모리 인덱스를 JSON 캐시 파일로 원자적으로 저장."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "created_at": datetime.now().isoformat(),
                "count": len(self.companies),
                "companies": self.companies,
            }
            tmp = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                suffix=".json",
                dir=self.cache_dir,
            )
            try:
                json.dump(payload, tmp, ensure_ascii=False, default=str)
                tmp.close()
                os.replace(tmp.name, self.cache_path)
            except Exception:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass
                raise
        except Exception as e:
            logger.warning("DART 인덱스 캐시 저장 실패: %s", e)

    def _load_cache(self) -> bool:
        """캐시 파일에서 인덱스를 불러옵니다."""
        if not self.cache_path.exists():
            return False
        try:
            mtime = datetime.fromtimestamp(self.cache_path.stat().st_mtime)
            if datetime.now() - mtime > self.refresh_interval:
                return False
            with open(self.cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            with self._lock:
                self.companies = payload.get("companies", [])
                self._loaded = bool(self.companies)
                self._last_loaded_at = mtime
                self._last_error = None
            logger.info("DART 인덱스 캐시 로드 완료: %s 건", len(self.companies))
            return True
        except Exception as e:
            logger.warning("DART 인덱스 캐시 로드 실패: %s", e)
            return False

    # --------------------------------------------------------------------------
    # DART 데이터 수집
    # --------------------------------------------------------------------------

    def _fetch_corp_codes(self) -> List[Dict[str, str]]:
        """DART 고유번호 XML(zip)을 다운로드 및 파싱."""
        logger.info("DART corpCode.xml 다운로드 시작")
        try:
            resp = self.session.get(
                CORP_CODE_URL,
                params={"crtfc_key": self.api_key},
                timeout=20,
            )
            resp.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            logger.error("DART 연결 끊김 (corpCode.xml): %s", e)
            raise
        except Exception as e:
            logger.error("DART corpCode.xml 다운로드 실패: %s", e)
            raise

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
            corps.append({
                "corp_code": corp_code,
                "corp_name": corp_name,
                "stock_code": stock_code,
            })
        logger.info("DART 전체 기업 수: %s", len(corps))
        return corps

    def _fetch_company(self, corp: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """개별 기업개황 조회 후 금속 필터링에 필요한 최소 정보 반환."""
        try:
            resp = self.session.get(
                COMPANY_URL,
                params={"crtfc_key": self.api_key, "corp_code": corp["corp_code"]},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.ConnectionError as e:
            logger.debug("DART company.json 연결 오류 (%s): %s", corp["corp_code"], e)
            return None
        except Exception as e:
            logger.debug("DART company.json 조회 실패 (%s): %s", corp["corp_code"], e)
            return None

        if "adres" not in data:
            return None

        adres = data.get("adres", "")
        induty_code = data.get("induty_code", "")
        corp_name = data.get("corp_name") or corp["corp_name"]

        if not is_metal_related(corp_name, induty_code):
            return None

        return {
            "corp_code": data.get("corp_code") or corp["corp_code"],
            "corp_name": corp_name,
            "stock_code": data.get("stock_code") or corp.get("stock_code", ""),
            "adres": adres,
            "sigungu": extract_sigungu(adres),
            "induty_code": induty_code,
            "induty_name": self._get_induty_name(induty_code),
            "ceo_nm": data.get("ceo_nm", ""),
            "phn_no": data.get("phn_no", ""),
            "fax_no": data.get("fax_no", ""),
            "bizr_no": data.get("bizr_no", ""),
            "hm_url": data.get("hm_url", ""),
        }

    # --------------------------------------------------------------------------
    # 인덱스 구축/갱신
    # --------------------------------------------------------------------------

    def _build_index(self) -> None:
        """전체 기업 중 금속 기업만 추려 메모리/캐시에 저장."""
        logger.info("DART 금속 기업 인덱스 구축 시작")
        self._loading = True
        self._last_error = None

        try:
            corps = self._fetch_corp_codes()

            # 1차: 기업명으로 후보 필터 (company.json 호출 최소화)
            name_candidates = [c for c in corps if is_metal_name(c["corp_name"])]
            logger.info("DART 기업명 1차 필터 후보: %s 건", len(name_candidates))

            metal_companies: List[Dict[str, Any]] = []
            total = len(name_candidates)
            for i in range(0, total, self.chunk_size):
                chunk = name_candidates[i : i + self.chunk_size]
                chunk_results: List[Dict[str, Any]] = []
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_corp = {
                        executor.submit(self._fetch_company, c): c for c in chunk
                    }
                    for future in as_completed(future_to_corp):
                        try:
                            info = future.result(timeout=15)
                        except Exception:
                            info = None
                        if info:
                            chunk_results.append(info)

                metal_companies.extend(chunk_results)
                logger.info(
                    "DART 인덱스 진행: %s/%s (누적 금속 기업 %s)",
                    min(i + self.chunk_size, total),
                    total,
                    len(metal_companies),
                )

                # rate limit 완화 및 중간 캐싱
                with self._lock:
                    self.companies = metal_companies.copy()
                self._save_cache()
                if i + self.chunk_size < total:
                    time.sleep(0.6)

            with self._lock:
                self.companies = metal_companies
                self._loaded = True
                self._last_loaded_at = datetime.now()
                self._last_error = None

            self._save_cache()
            logger.info("DART 금속 기업 인덱스 구축 완료: %s 건", len(metal_companies))
        except Exception as e:
            self._last_error = str(e)
            logger.exception("DART 인덱스 구축 중 오류: %s", e)
            raise
        finally:
            self._loading = False

    def _load_or_build(self) -> None:
        """캐시를 먼저 시도하고, 실패/오래되면 인덱스를 새로 구축."""
        if self._load_cache():
            return
        try:
            self._build_index()
        except Exception:
            # 백그라운드에서 실행될 때 상위에서 로깅만 하고 멈추지 않음
            pass

    def start_background_refresh(self) -> None:
        """별도 스레드에서 인덱스 구축/갱신을 시작."""
        if self._loading or (self._refresh_thread and self._refresh_thread.is_alive()):
            return
        self._refresh_thread = threading.Thread(target=self._load_or_build, daemon=True)
        self._refresh_thread.start()

    def trigger_refresh(self) -> bool:
        """동기적으로 인덱스를 강제 갱신 (주의: 시간이 오래 소요될 수 있음)."""
        try:
            self._build_index()
            return True
        except Exception:
            return False

    # --------------------------------------------------------------------------
    # 검색 API
    # --------------------------------------------------------------------------

    def is_ready(self) -> bool:
        with self._lock:
            return self._loaded

    def is_loading(self) -> bool:
        return self._loading

    def _search_all(self, keyword: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            data = self.companies.copy()
        if not keyword or not keyword.strip():
            return data
        kw = keyword.strip().lower()
        return [
            c
            for c in data
            if kw in c["corp_name"].lower()
            or (c.get("induty_name") and kw in c["induty_name"].lower())
            or (c.get("adres") and kw in c["adres"].lower())
        ]

    def search_by_name(self, keyword: str, limit: int = 100) -> List[Dict[str, Any]]:
        """기업명 키워드로 내부 인덱스 검색 (외부 API 호출 없음)."""
        results = self._search_all(keyword)
        return results[:limit]

    def search_by_region(
        self, region_name: str, keyword: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """시군구 기준 내부 인덱스 검색. keyword 가 있으면 기업명으로 추가 필터."""
        region_key = (extract_sigungu(region_name) or region_name).strip()
        with self._lock:
            data = self.companies.copy()

        results = [c for c in data if c.get("sigungu") == region_key]
        if keyword and keyword.strip():
            kw = keyword.strip().lower()
            results = [c for c in results if kw in c["corp_name"].lower()]
        return results[:limit]

    def get_company_detail(self, corp_code: str) -> Optional[Dict[str, Any]]:
        """특정 기업의 상세 정보를 DART API 로 실시간 조회."""
        try:
            resp = self.session.get(
                COMPANY_URL,
                params={"crtfc_key": self.api_key, "corp_code": corp_code},
                timeout=12,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError as e:
            logger.error("DART 상세정보 연결 끊김 (%s): %s", corp_code, e)
            return None
        except Exception as e:
            logger.error("DART 상세정보 조회 실패 (%s): %s", corp_code, e)
            return None

    def get_financial_statements(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = "11011",
    ) -> Optional[Dict[str, Any]]:
        """특정 기업/년도/보고서의 재무제표를 DART API 로 실시간 조회."""
        try:
            resp = self.session.get(
                FINANCIAL_URL,
                params={
                    "crtfc_key": self.api_key,
                    "corp_code": corp_code,
                    "bsns_year": bsns_year,
                    "reprt_code": reprt_code,
                    "fs_div": "OFS",
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError as e:
            logger.error("DART 재무제표 연결 끊김 (%s): %s", corp_code, e)
            return None
        except Exception as e:
            logger.error("DART 재무제표 조회 실패 (%s): %s", corp_code, e)
            return None

    # --------------------------------------------------------------------------
    # 상태
    # --------------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "api_key_set": bool(self.api_key),
                "loaded": self._loaded,
                "loading": self._loading,
                "company_count": len(self.companies),
                "last_loaded_at": (
                    self._last_loaded_at.isoformat() if self._last_loaded_at else None
                ),
                "last_error": self._last_error,
                "cache_path": str(self.cache_path),
            }


def create_dart_index(api_key: Optional[str] = None) -> Optional[DartCompanyIndex]:
    """환경변수 DART_API_KEY 를 기반으로 인덱스를 생성."""
    key = api_key or os.environ.get("DART_API_KEY")
    if not key:
        return None
    return DartCompanyIndex(key)


if __name__ == "__main__":
    key = os.environ.get("DART_API_KEY")
    if not key:
        print("DART_API_KEY 환경변수를 설정해주세요.")
    else:
        idx = DartCompanyIndex(key)
        idx.trigger_refresh()
        print("금속 기업 수:", len(idx.companies))
        print(idx.search_by_region("울산광역시 울주군", keyword="철강"))
