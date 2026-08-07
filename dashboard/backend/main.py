# -*- coding: utf-8 -*-
"""
FastAPI 백엔드: 시군구별 금속 수입 데이터 API (관세청 API 직접 호출 + JSON 파일 캐싱)

서버 시작 시 `data_cache.json` 파일이 있으면 즉시 로드하고, 없을 경우에만
백그라운드에서 관세청 시군구별 품목별 수출입실적 API를 호출한다.
/api/refresh 호출 시 API를 재호출하여 캐시 파일을 갱신한다.

엔드포인트
----------
GET  /api/health
GET  /api/status
    - 데이터 캐시 상태(수집 진행 여부, 마지막 갱신 시각, 행 수)
POST /api/refresh
    - 관세청 API를 다시 호출해 캐시를 갱신한다 (백그라운드 실행, 즉시 응답)
GET  /api/regions
    - 시군구별 총 수입금액(USD)/수입건수 요약 목록 (지도/바 차트용)
GET  /api/regions/{region_name}/breakdown
    - 특정 시군구의 금속별 수입 비율 (클릭 시 상세 패널용)
GET  /api/regions/{region_name}/timeseries
    - 특정 시군구의 연월별 수입금액 추이

실행
----
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

# 프로젝트 루트의 sigungu_metal_import_collector.py 를 import 하기 위한 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import sigungu_metal_import_collector as collector  # noqa: E402
from dart_company_index import DartCompanyIndex, create_dart_index  # noqa: E402

_dart_index: Optional[DartCompanyIndex] = None


def _get_dart_index() -> Optional[DartCompanyIndex]:
    global _dart_index
    if _dart_index is None:
        _dart_index = create_dart_index()
    return _dart_index

# ------------------------------------------------------------------------------
# 설정
# ------------------------------------------------------------------------------

DEFAULT_STRT_YYMM = os.environ.get("METAL_STRT_YYMM", "202401")
DEFAULT_END_YYMM = os.environ.get("METAL_END_YYMM", "202412")
# 데이터 캐시는 Parquet(바이너리 컬럼형 포맷)으로 저장한다.
# JSON 대비 파일 크기와 로드 시 메모리 사용량이 훨씬 작고 파싱 속도도 빠르다.
CACHE_FILE = Path(__file__).resolve().parents[2] / "data_cache.parquet"
CACHE_META_FILE = Path(__file__).resolve().parents[2] / "data_cache_meta.json"
# 이전 버전(JSON 캐시)과의 하위 호환을 위한 경로. 존재하면 1회 마이그레이션한다.
LEGACY_JSON_CACHE_FILE = Path(__file__).resolve().parents[2] / "data_cache.json"
LAST_AUTO_UPDATE_FILE = Path(__file__).resolve().parents[2] / ".last_auto_update"
# 캐시 스키마 버전. v2부터 "수입금액(USD)"가 천 달러가 아닌 실제 달러 금액이다.
CACHE_SCHEMA_VERSION = 2

# 엑셀 내보내기 캐시 디렉터리 (서버 임시 디렉터리 사용).
# 데이터가 갱신되기 전까지는 동일한 요청(region_name)에 대해 이 디렉터리에
# 저장된 파일을 그대로 재사용하여 매번 6만+ 행을 다시 생성하지 않는다.
EXPORT_CACHE_DIR = Path(tempfile.gettempdir()) / "sigungu_metal_import_cache"
AUTO_UPDATE_DAY_START = int(os.environ.get("METAL_AUTO_UPDATE_DAY_START", "15"))
AUTO_UPDATE_DAY_END = int(os.environ.get("METAL_AUTO_UPDATE_DAY_END", "20"))
AUTO_UPDATE_HOUR = int(os.environ.get("METAL_AUTO_UPDATE_HOUR", "9"))

app = FastAPI(title="시군구별 금속 수입 대시보드 API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 운영 환경에서는 프론트엔드 도메인으로 제한 권장
    allow_methods=["*"],
    allow_headers=["*"],
)

# 시군구명 -> 대표 좌표 (경도, 위도). 프론트엔드 버블맵에서 사용.
# 정확한 매칭이 없으면 시도명으로 SIDO_CENTER_COORDINATES 를 fallback으로 사용한다.
REGION_COORDINATES = {
    "경상북도 포항시": {"lat": 36.0190, "lon": 129.3435},
    "울산광역시 남구": {"lat": 35.5372, "lon": 129.3300},
    "충청남도 당진시": {"lat": 36.8930, "lon": 126.6280},
    "전라남도 광양시": {"lat": 34.9407, "lon": 127.6959},
    "전라남도 여수시": {"lat": 34.7604, "lon": 127.6622},
}

SIDO_CENTER_COORDINATES = {
    "서울특별시": {"lat": 37.5665, "lon": 126.9780},
    "부산광역시": {"lat": 35.1796, "lon": 129.0756},
    "대구광역시": {"lat": 35.8714, "lon": 128.6014},
    "인천광역시": {"lat": 37.4563, "lon": 126.7052},
    "광주광역시": {"lat": 35.1595, "lon": 126.8526},
    "대전광역시": {"lat": 36.3504, "lon": 127.3845},
    "울산광역시": {"lat": 35.5384, "lon": 129.3114},
    "세종특별자치시": {"lat": 36.4801, "lon": 127.2891},
    "경기도": {"lat": 37.4138, "lon": 127.5183},
    "강원특별자치도": {"lat": 37.8228, "lon": 128.1555},
    "충청북도": {"lat": 36.8000, "lon": 127.7000},
    "충청남도": {"lat": 36.5184, "lon": 126.8000},
    "전북특별자치도": {"lat": 35.7175, "lon": 127.1530},
    "전라남도": {"lat": 34.8161, "lon": 126.4630},
    "경상북도": {"lat": 36.4919, "lon": 128.8889},
    "경상남도": {"lat": 35.4606, "lon": 128.2132},
    "제주특별자치도": {"lat": 33.4996, "lon": 126.5312},
}


def resolve_coordinates(region_nm: str) -> dict:
    if region_nm in REGION_COORDINATES:
        return REGION_COORDINATES[region_nm]
    for sido_nm, coord in SIDO_CENTER_COORDINATES.items():
        if region_nm.startswith(sido_nm):
            return coord
    return {}


# ------------------------------------------------------------------------------
# 관세청 API 실시간 수집 및 인메모리 캐싱
# ------------------------------------------------------------------------------

class DataCache:
    def __init__(self) -> None:
        self.df: pd.DataFrame = pd.DataFrame()
        self.is_refreshing: bool = False
        self.last_updated: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.loaded_from_cache: bool = False
        self._lock = threading.Lock()
        self._load_cache()

    def _load_cache(self) -> None:
        """로컬 Parquet 캐시 파일이 있으면 메모리에 1회 로드한다.

        이후 모든 API 엔드포인트는 디스크를 다시 읽지 않고 이 메모리
        데이터프레임(self.df)에서만 조회한다.
        """
        try:
            meta = self._read_meta()
            if CACHE_FILE.exists():
                df = pd.read_parquet(CACHE_FILE, engine="pyarrow")
                last_updated = self._read_meta_timestamp() or datetime.fromtimestamp(
                    CACHE_FILE.stat().st_mtime
                )
            elif LEGACY_JSON_CACHE_FILE.exists():
                # 구버전 JSON 캐시가 남아있다면 1회 마이그레이션한다.
                with open(LEGACY_JSON_CACHE_FILE, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                df = pd.DataFrame(payload["rows"])
                last_updated = (
                    datetime.fromisoformat(payload["last_updated"])
                    if payload.get("last_updated")
                    else datetime.fromtimestamp(LEGACY_JSON_CACHE_FILE.stat().st_mtime)
                )
                if not df.empty:
                    self._save_cache(df, last_updated)
            else:
                return

            if df.empty:
                return

            if meta.get("schema_version", 1) < 2 and "수입금액(USD)" in df.columns:
                df["수입금액(USD)"] = df["수입금액(USD)"] * collector.USD_AMOUNT_UNIT
                self._save_cache(df, last_updated)

            with self._lock:
                self.df = df
                self.last_updated = last_updated
                self.loaded_from_cache = True
                self.last_error = None
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.last_error = f"캐시 파일 로드 실패: {exc}"

    @staticmethod
    def _read_meta() -> Dict[str, Any]:
        if not CACHE_META_FILE.exists():
            return {}
        try:
            with open(CACHE_META_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}

    @classmethod
    def _read_meta_timestamp(cls) -> Optional[datetime]:
        ts = cls._read_meta().get("last_updated")
        try:
            return datetime.fromisoformat(ts) if ts else None
        except Exception:  # noqa: BLE001
            return None

    def _save_cache(self, df: pd.DataFrame, last_updated: datetime) -> None:
        """데이터프레임을 Parquet 파일 + 메타데이터(JSON)로 저장한다."""
        df.to_parquet(CACHE_FILE, engine="pyarrow", index=False)
        with open(CACHE_META_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "last_updated": last_updated.isoformat(),
                    "schema_version": CACHE_SCHEMA_VERSION,
                },
                f,
                ensure_ascii=False,
            )

    def start_refresh(self, strt_yymm: str, end_yymm: str) -> None:
        with self._lock:
            if self.is_refreshing:
                return
            self.is_refreshing = True
            self.last_error = None

        thread = threading.Thread(
            target=self._run_refresh, args=(strt_yymm, end_yymm), daemon=True
        )
        thread.start()

    def _run_refresh(self, strt_yymm: str, end_yymm: str) -> None:
        try:
            df = collector.collect_all_import_data(
                strt_yymm=strt_yymm,
                end_yymm=end_yymm,
                hs6_codes=collector.TARGET_HS6_CODES,
                sido_map=collector.TARGET_SIDO_MAP,
                sigungu_keywords=collector.TARGET_SIGUNGU_KEYWORDS,
            )
            if df is None or df.empty:
                raise ValueError("수집된 데이터가 없습니다.")
            now = datetime.now()
            with self._lock:
                self.df = df
                self.last_updated = now
                self.loaded_from_cache = False
            self._save_cache(df, now)
            invalidate_excel_cache()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.last_error = str(exc)
        finally:
            with self._lock:
                self.is_refreshing = False

    def get_df(self) -> pd.DataFrame:
        with self._lock:
            return self.df.copy()


cache = DataCache()

# DART 기업 본사-시군구 매핑 (dart_company_collector.py 가 생성한 dart_company_map.json)
REGION_COMPANIES: Dict[str, List[Dict[str, Any]]] = {}


def load_region_companies() -> None:
    global REGION_COMPANIES
    map_path = Path(__file__).resolve().parent / "dart_company_map.json"
    if map_path.exists():
        with open(map_path, "r", encoding="utf-8") as f:
            REGION_COMPANIES = json.load(f)


# DART 기업 매핑 즉시 로드 (개발/테스트 및 uvicorn startup 모두에서 사용 가능)
load_region_companies()


def _previous_month_yymm(today: date) -> str:
    """이전 달을 'YYYYMM' 형식으로 반환한다."""
    first_of_month = today.replace(day=1)
    last_month = first_of_month - timedelta(days=1)
    return last_month.strftime("%Y%m")


def _seconds_until_next_0900() -> float:
    """다음 오전 9시까지 남은 초를 반환한다."""
    now = datetime.now()
    next_0900 = now.replace(hour=AUTO_UPDATE_HOUR, minute=0, second=0, microsecond=0)
    if next_0900 <= now:
        next_0900 += timedelta(days=1)
    return (next_0900 - now).total_seconds()


def _mark_update_done(target_yymm: str) -> None:
    """수집이 끝나고 성공하면 마지막 자동 업데이트 시점을 기록한다."""
    start = time.time()
    timeout = 7200  # 최대 2시간 대기
    while cache.is_refreshing and time.time() - start < timeout:
        time.sleep(5)

    if not cache.is_refreshing and not cache.last_error:
        try:
            LAST_AUTO_UPDATE_FILE.write_text(target_yymm, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def _try_monthly_update() -> None:
    """매월 15~20일 사이에 아직 업데이트하지 않았다면 전월 기준으로 데이터를 갱신한다."""
    today = date.today()
    if not (AUTO_UPDATE_DAY_START <= today.day <= AUTO_UPDATE_DAY_END):
        return

    target_yymm = _previous_month_yymm(today)
    if LAST_AUTO_UPDATE_FILE.exists():
        try:
            last = LAST_AUTO_UPDATE_FILE.read_text(encoding="utf-8").strip()
            if last == target_yymm:
                return
        except Exception:  # noqa: BLE001
            pass

    logger = collector.logger if hasattr(collector, "logger") else None
    if logger:
        logger.info(
            "월간 자동 업데이트 시작: %s ~ %s", DEFAULT_STRT_YYMM, target_yymm
        )
    cache.start_refresh(DEFAULT_STRT_YYMM, target_yymm)
    threading.Thread(
        target=_mark_update_done, args=(target_yymm,), daemon=True
    ).start()


def _monthly_update_scheduler() -> None:
    """매일 09:00에 한 번씩 월간 업데이트 가능 시점을 확인한다."""
    _try_monthly_update()
    while True:
        time.sleep(_seconds_until_next_0900())
        _try_monthly_update()


@app.on_event("startup")
def on_startup() -> None:
    # DART 기업 매핑이 있으면 로드
    load_region_companies()
    # 캐시 파일이 있으면 로드하여 즉시 서비스하고, 없을 때만 API 수집을 시작한다.
    if cache.df.empty:
        cache.start_refresh(DEFAULT_STRT_YYMM, DEFAULT_END_YYMM)
    # DART 금속 기업 인덱스는 사전 빌드된 JSON 파일에서 로드 (백그라운드 크롤링 금지)
    _get_dart_index()
    # 월 1회(15~20일) 자동 업데이트 스케줄러 실행
    threading.Thread(target=_monthly_update_scheduler, daemon=True).start()


# ------------------------------------------------------------------------------
# 응답 스키마
# ------------------------------------------------------------------------------

class RegionSummary(BaseModel):
    region_nm: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    total_import_usd: float
    total_import_cnt: int


class MetalBreakdownItem(BaseModel):
    metal_category: str
    import_usd: float
    import_cnt: int
    ratio_pct: float


class TimeseriesPoint(BaseModel):
    year_month: str
    import_usd: float
    import_cnt: int


class MetalSummary(BaseModel):
    metal_category: str
    total_import_usd: float
    total_import_cnt: int


class MetalRegionItem(BaseModel):
    region_nm: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    import_usd: float
    import_cnt: int
    ratio_pct: float


class RegionCompany(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: str = ""
    adres: str
    sigungu: str = ""
    induty_code: str = ""
    induty_name: str = ""
    ceo_nm: str = ""
    phn_no: str = ""
    fax_no: str = ""
    bizr_no: str = ""
    hm_url: str = ""
    revenue: str = ""
    op_profit: str = ""
    fin_year: str = ""
    fs_type: str = ""


class RegionCompaniesResponse(BaseModel):
    companies: List[RegionCompany]
    index_loaded: bool
    message: str = ""


# ------------------------------------------------------------------------------
# 엔드포인트
# ------------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/status")
def get_status() -> dict:
    return {
        "is_refreshing": cache.is_refreshing,
        "last_updated": cache.last_updated.isoformat() if cache.last_updated else None,
        "last_error": cache.last_error,
        "row_count": len(cache.df),
        "loaded_from_cache": cache.loaded_from_cache,
        "cache_file_exists": CACHE_FILE.exists(),
        "cache_file_path": str(CACHE_FILE),
        "cache_format": "parquet",
    }


@app.post("/api/refresh")
def refresh(strt_yymm: str = DEFAULT_STRT_YYMM, end_yymm: str = DEFAULT_END_YYMM) -> dict:
    """관세청 API를 다시 호출해 백그라운드에서 캐시를 갱신한다 (즉시 반환)."""
    if cache.is_refreshing:
        return {"status": "already_refreshing"}
    cache.start_refresh(strt_yymm, end_yymm)
    return {"status": "started", "strt_yymm": strt_yymm, "end_yymm": end_yymm}


def _get_df_or_503() -> pd.DataFrame:
    df = cache.get_df()
    if df.empty:
        if cache.is_refreshing:
            raise HTTPException(status_code=425, detail="데이터 수집이 진행 중입니다. 잠시 후 다시 시도하세요.")
        if cache.last_error:
            raise HTTPException(status_code=502, detail=f"데이터 수집 실패: {cache.last_error}")
        raise HTTPException(status_code=404, detail="수집된 데이터가 없습니다. POST /api/refresh 를 호출하세요.")
    return df


@app.get("/api/dart-status")
def dart_status() -> Dict[str, Any]:
    """DART API 키 설정 및 사전 빌드 인덱스 상태 확인."""
    idx = _get_dart_index()
    ready = idx.is_ready() if idx else False
    status = idx.status() if idx else None
    return {
        "dart_api_key_set": bool(os.environ.get("DART_API_KEY")),
        "index_ready": ready,
        "index_status": status,
        "message": (
            "DART 인덱스가 로드되었습니다."
            if ready
            else "dart_metal_index.json 파일이 없거나 비어 있습니다. build_dart_metal_index.py 를 실행하여 파일을 생성해주세요."
        ),
    }


@app.get("/api/region-companies", response_model=RegionCompaniesResponse)
def get_region_companies(region_name: str, keyword: str = "") -> RegionCompaniesResponse:
    """선택한 시군구에 본사/등록 사업장을 둔 DART 기업 목록 반환.

    사전 빌드된 dart_metal_index.json 파일이 있으면 이를 사용하고,
    없으면 상태 메시지와 함께 빈 목록을 반환합니다.
    """
    idx = _get_dart_index()
    if idx and idx.is_ready():
        companies = idx.search_by_region(region_name, keyword=keyword or None)
        return RegionCompaniesResponse(
            companies=companies, index_loaded=True, message=""
        )

    load_region_companies()  # dart_company_map.json 변경 시 재시작 없이 반영
    fallback = REGION_COMPANIES.get(region_name, [])
    if fallback:
        return RegionCompaniesResponse(
            companies=fallback, index_loaded=False, message="DART 인덱스 대신 캐시 파일을 사용합니다."
        )

    return RegionCompaniesResponse(
        companies=[],
        index_loaded=False,
        message="DART 인덱스가 로드되지 않았습니다. build_dart_metal_index.py 를 실행하여 dart_metal_index.json 을 생성해주세요.",
    )


@app.get("/api/companies/search", response_model=RegionCompaniesResponse)
def search_companies(keyword: str) -> RegionCompaniesResponse:
    """기업명/업종/주소 키워드로 DART 기업을 검색하고, 시군구(sigungu) 정보와 함께 반환."""
    idx = _get_dart_index()
    if idx and idx.is_ready():
        companies = idx.search_by_name(keyword)
        return RegionCompaniesResponse(
            companies=companies, index_loaded=True, message=""
        )

    return RegionCompaniesResponse(
        companies=[],
        index_loaded=False,
        message="DART 인덱스가 로드되지 않았습니다. build_dart_metal_index.py 를 실행하여 dart_metal_index.json 을 생성해주세요.",
    )


@app.get("/api/regions", response_model=List[RegionSummary])
def get_regions() -> List[RegionSummary]:
    df = _get_df_or_503()

    grouped = (
        df.groupby("시군구명", as_index=False)
        .agg(total_import_usd=("수입금액(USD)", "sum"), total_import_cnt=("수입건수", "sum"))
        .sort_values("total_import_usd", ascending=False)
    )

    results: List[RegionSummary] = []
    for _, row in grouped.iterrows():
        coord = resolve_coordinates(row["시군구명"])
        results.append(
            RegionSummary(
                region_nm=row["시군구명"],
                lat=coord.get("lat"),
                lon=coord.get("lon"),
                total_import_usd=float(row["total_import_usd"]),
                total_import_cnt=int(row["total_import_cnt"]),
            )
        )
    return results


@app.get("/api/regions/{region_name}/breakdown", response_model=List[MetalBreakdownItem])
def get_region_breakdown(region_name: str) -> List[MetalBreakdownItem]:
    df = _get_df_or_503()

    region_df = df[df["시군구명"] == region_name]
    if region_df.empty:
        raise HTTPException(status_code=404, detail=f"'{region_name}' 데이터가 없습니다.")

    grouped = (
        region_df.groupby("금속구분", as_index=False)
        .agg(import_usd=("수입금액(USD)", "sum"), import_cnt=("수입건수", "sum"))
        .sort_values("import_usd", ascending=False)
    )

    total = grouped["import_usd"].sum()
    results: List[MetalBreakdownItem] = []
    for _, row in grouped.iterrows():
        ratio = (row["import_usd"] / total * 100) if total > 0 else 0.0
        results.append(
            MetalBreakdownItem(
                metal_category=row["금속구분"],
                import_usd=float(row["import_usd"]),
                import_cnt=int(row["import_cnt"]),
                ratio_pct=round(float(ratio), 2),
            )
        )
    return results


@app.get("/api/regions/{region_name}/timeseries", response_model=List[TimeseriesPoint])
def get_region_timeseries(region_name: str) -> List[TimeseriesPoint]:
    df = _get_df_or_503()

    region_df = df[df["시군구명"] == region_name]
    if region_df.empty:
        raise HTTPException(status_code=404, detail=f"'{region_name}' 데이터가 없습니다.")

    grouped = (
        region_df.groupby("연월", as_index=False)
        .agg(import_usd=("수입금액(USD)", "sum"), import_cnt=("수입건수", "sum"))
        .sort_values("연월")
    )

    return [
        TimeseriesPoint(
            year_month=row["연월"],
            import_usd=float(row["import_usd"]),
            import_cnt=int(row["import_cnt"]),
        )
        for _, row in grouped.iterrows()
    ]


@app.get("/api/metals", response_model=List[MetalSummary])
def get_metals() -> List[MetalSummary]:
    """전체 금속(금속구분)별 총 수입금액/건수를 반환한다."""
    df = _get_df_or_503()

    grouped = (
        df.groupby("금속구분", as_index=False)
        .agg(total_import_usd=("수입금액(USD)", "sum"), total_import_cnt=("수입건수", "sum"))
        .sort_values("total_import_usd", ascending=False)
    )

    return [
        MetalSummary(
            metal_category=row["금속구분"],
            total_import_usd=float(row["total_import_usd"]),
            total_import_cnt=int(row["total_import_cnt"]),
        )
        for _, row in grouped.iterrows()
    ]


@app.get("/api/metals/{metal_category}/regions", response_model=List[MetalRegionItem])
def get_metal_regions(metal_category: str, limit: int = 20) -> List[MetalRegionItem]:
    """특정 금속을 가장 많이 수입하는 시군구 순위를 반환한다."""
    df = _get_df_or_503()

    metal_df = df[df["금속구분"] == metal_category]
    if metal_df.empty:
        raise HTTPException(status_code=404, detail=f"'{metal_category}' 데이터가 없습니다.")

    grouped = (
        metal_df.groupby("시군구명", as_index=False)
        .agg(import_usd=("수입금액(USD)", "sum"), import_cnt=("수입건수", "sum"))
        .sort_values("import_usd", ascending=False)
    )

    total = float(grouped["import_usd"].sum())
    results: List[MetalRegionItem] = []
    for _, row in grouped.head(limit).iterrows():
        coord = resolve_coordinates(row["시군구명"])
        ratio = (row["import_usd"] / total * 100) if total > 0 else 0.0
        results.append(
            MetalRegionItem(
                region_nm=row["시군구명"],
                lat=coord.get("lat"),
                lon=coord.get("lon"),
                import_usd=float(row["import_usd"]),
                import_cnt=int(row["import_cnt"]),
                ratio_pct=round(float(ratio), 2),
            )
        )
    return results


_excel_cache_lock = threading.Lock()


def _excel_cache_path(region_name: Optional[str]) -> Path:
    """region_name별 캐시 파일 경로를 반환한다."""
    if region_name:
        safe_name = "".join(
            c if (c.isalnum() or c in ("-", "_")) else "_" for c in region_name
        )
        return EXPORT_CACHE_DIR / f"sigungu_metal_import_cache__{safe_name}.xlsx"
    return EXPORT_CACHE_DIR / "sigungu_metal_import_cache.xlsx"


def invalidate_excel_cache() -> None:
    """원본 데이터가 갱신될 때 캐시된 엑셀 파일들을 모두 삭제한다.

    파일 접근/삭제 실패는 무시한다 (캐시가 없어도 다음 요청에서 새로 생성되므로
    서비스 동작에는 영향이 없다).
    """
    try:
        if not EXPORT_CACHE_DIR.exists():
            return
        with _excel_cache_lock:
            for f in EXPORT_CACHE_DIR.glob("*.xlsx"):
                try:
                    os.remove(f)
                except OSError:
                    pass
    except Exception:  # noqa: BLE001
        pass


def _build_excel_file(df: pd.DataFrame, region_name: Optional[str], dest: Path) -> None:
    """엑셀 워크북을 생성하여 dest 경로에 저장한다.

    임시 파일(.tmp)에 먼저 쓰고 성공 시에만 원자적으로 rename하여, 생성 도중
    오류가 발생해도 손상된 파일이 캐시로 남지 않도록 한다.
    """
    tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
    try:
        # xlsxwriter는 openpyxl보다 문자열 처리/내부 자료구조가 가벼워 메모리 사용량이
        # 적다. (constant_memory 옵션은 pandas의 열 단위 기록 방식과 호환되지 않아
        # 데이터가 유실되는 문제가 있어 사용하지 않는다.)
        with pd.ExcelWriter(tmp_dest, engine="xlsxwriter") as writer:
            _write_export_sheets(writer, df, region_name)
        os.replace(tmp_dest, dest)
    except MemoryError as exc:
        _safe_remove(tmp_dest)
        raise HTTPException(
            status_code=507,
            detail=f"엑셀 생성 중 메모리가 부족합니다: {exc}",
        ) from exc
    except HTTPException:
        _safe_remove(tmp_dest)
        raise
    except Exception as exc:  # noqa: BLE001
        _safe_remove(tmp_dest)
        raise HTTPException(
            status_code=500,
            detail=f"엑셀 생성 중 오류가 발생했습니다: {exc}",
        ) from exc


def _safe_remove(path: Path) -> None:
    try:
        if path.exists():
            os.remove(path)
    except OSError:
        pass


@app.get("/api/export/excel")
def export_excel(
    region_name: Optional[str] = Query(None, description="특정 시군구를 지정하면 해당 지역 중심의 워크북을 생성합니다.")
) -> FileResponse:
    """현재 데이터를 엑셀(.xlsx)로 내보냅니다.

    - region_name 미지정: 전체 시군구·금속 요약 + 시군구×금속 매트릭스 + 원본 데이터
    - region_name 지정: 요약 + 선택 시군구의 금속별 비중/추이 + 해당 지역 원본 데이터

    서버 임시 디렉터리(EXPORT_CACHE_DIR)에 생성된 파일을 캐싱하여 재사용한다.
    캐시 파일이 있으면 즉시 반환하고(디스크에서 스트리밍, 재생성 없음),
    없으면(최초 요청 또는 데이터 갱신으로 캐시가 삭제된 이후) 새로 생성 후 저장한다.
    """
    cache_path = _excel_cache_path(region_name)

    with _excel_cache_lock:
        if not cache_path.exists():
            df = _get_df_or_503()
            try:
                EXPORT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise HTTPException(
                    status_code=500, detail=f"캐시 디렉터리 생성 실패: {exc}"
                ) from exc
            _build_excel_file(df, region_name, cache_path)

    filename = "sigungu_metal_import.xlsx" if not region_name else (
        f"sigungu_metal_import_{region_name.replace(' ', '_')}.xlsx"
    )
    encoded = quote(filename)
    return FileResponse(
        path=cache_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


def _write_export_sheets(
    writer: "pd.ExcelWriter", df: pd.DataFrame, region_name: Optional[str]
) -> None:
    """엑셀 워크북에 필요한 시트만 필터링하여 순서대로 기록한다."""
    # 1) 시군구별 요약
    region_summary = (
        df.groupby("시군구명", as_index=False)
        .agg(
            총수입금액=("수입금액(USD)", "sum"),
            총수입건수=("수입건수", "sum"),
        )
        .sort_values("총수입금액", ascending=False)
    )
    region_summary.to_excel(writer, sheet_name="시군구별_요약", index=False)

    # 2) 금속별 요약
    metal_summary = (
        df.groupby("금속구분", as_index=False)
        .agg(
            총수입금액=("수입금액(USD)", "sum"),
            총수입건수=("수입건수", "sum"),
        )
        .sort_values("총수입금액", ascending=False)
    )
    metal_summary.to_excel(writer, sheet_name="금속별_요약", index=False)

    # 3) 시군구 × 금속 매트릭스
    pivot = df.pivot_table(
        index="시군구명",
        columns="금속구분",
        values="수입금액(USD)",
        aggfunc="sum",
        fill_value=0,
    )
    pivot.to_excel(writer, sheet_name="시군구_금속별_금액")

    # 4) 원본 데이터 (전체 또는 선택 시군구)
    target_df = df[df["시군구명"] == region_name] if region_name else df
    if target_df.empty:
        raise HTTPException(status_code=404, detail=f"'{region_name}' 데이터가 없습니다.")

    target_df.to_excel(writer, sheet_name="원본_데이터", index=False)

    # 5) 선택 시군구 전용 시트
    if region_name:
        breakdown = (
            target_df.groupby("금속구분", as_index=False)
            .agg(
                수입금액=("수입금액(USD)", "sum"),
                수입건수=("수입건수", "sum"),
            )
            .sort_values("수입금액", ascending=False)
        )
        total = breakdown["수입금액"].sum()
        breakdown["비중(%)"] = (
            (breakdown["수입금액"] / total * 100).round(2) if total > 0 else 0.0
        )
        breakdown.to_excel(
            writer, sheet_name="선택_시군구_금속별", index=False
        )

        timeseries = (
            target_df.groupby("연월", as_index=False)
            .agg(
                수입금액=("수입금액(USD)", "sum"),
                수입건수=("수입건수", "sum"),
            )
            .sort_values("연월")
        )
        timeseries.to_excel(
            writer, sheet_name="선택_시군구_추이", index=False
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
