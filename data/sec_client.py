"""SEC EDGAR 클라이언트 — 미국 상장사 공시 재무제표 조회.

근거: 미국 증권거래위원회(https://www.sec.gov/edgar) 공식 데이터
라이선스: 17 U.S.C. § 105 — 미국 정부 저작물 = Public Domain (상업 이용 무제한)
호출 한도: 초당 10 요청 (User-Agent 헤더 필수)

yfinance가 부실 응답 줄 때 미국 종목 재무 데이터의 1차 소스로 사용.
DART(한국)와 동일한 인터페이스로 설계 → app.py가 같은 패턴으로 병합 가능.

API 문서: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
XBRL taxonomy: https://www.sec.gov/info/edgar/xbrlfinancialreporting.htm
"""
from __future__ import annotations

import os
import re
import time
import threading
from typing import Optional

import requests

from .cache import cache


# SEC 공식 엔드포인트
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_BASE = "https://data.sec.gov/api/xbrl/companyfacts"

# Rate limit + 매너 — User-Agent 필수
_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "StockInto stockintokr@gmail.com",  # 운영자 연락처 (SEC 가이드 따름)
)
_MIN_INTERVAL = 0.12  # 초당 8회 정도로 보수적 (SEC 한도 10/s)
_LAST_CALL = 0.0
_RATE_LOCK = threading.Lock()

# 티커 → CIK 매핑 (10자리 zero-padded)
_TICKER_TO_CIK: dict[str, str] = {}
_TICKER_LOCK = threading.Lock()
_TICKER_LOADED_AT: float = 0.0
_TICKER_TTL = 7 * 24 * 3600  # 7일


def is_available() -> bool:
    """SEC EDGAR는 공개라 항상 사용 가능 (네트워크 OK 가정)."""
    return True


def _throttle():
    global _LAST_CALL
    with _RATE_LOCK:
        now = time.time()
        wait = _MIN_INTERVAL - (now - _LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL = time.time()


def _headers() -> dict:
    """SEC가 요구하는 User-Agent 헤더."""
    return {"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip, deflate"}


def _normalize_ticker(ticker: str) -> Optional[str]:
    """미국 티커만 처리 — 한국 종목(.KS/.KQ)은 None."""
    if not ticker:
        return None
    t = ticker.strip().upper()
    # 한국 티커 차단
    if t.endswith(".KS") or t.endswith(".KQ"):
        return None
    # 거래소 접미사 제거 (예: BRK-B → BRK-B 그대로, AAPL.US → AAPL)
    if "." in t and not t.startswith("."):
        t = t.split(".")[0]
    # SEC는 일반적으로 영문/숫자/하이픈만
    if not re.fullmatch(r"[A-Z0-9\-]{1,10}", t):
        return None
    return t


def _load_ticker_map() -> dict[str, str]:
    """SEC company_tickers.json 받아서 ticker → CIK(10자리) 맵 구성. 7일 캐시.

    응답 구조:
        {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    """
    global _TICKER_LOADED_AT
    with _TICKER_LOCK:
        if _TICKER_TO_CIK and (time.time() - _TICKER_LOADED_AT) < _TICKER_TTL:
            return _TICKER_TO_CIK

        try:
            _throttle()
            r = requests.get(SEC_TICKERS_URL, headers=_headers(), timeout=15)
            r.raise_for_status()
            data = r.json()

            new_map: dict[str, str] = {}
            for entry in data.values():
                ticker = (entry.get("ticker") or "").upper().strip()
                cik = entry.get("cik_str")
                if ticker and isinstance(cik, int):
                    # CIK 10자리 zero-pad (SEC 표준)
                    new_map[ticker] = f"{cik:010d}"
            _TICKER_TO_CIK.clear()
            _TICKER_TO_CIK.update(new_map)
            _TICKER_LOADED_AT = time.time()
            return _TICKER_TO_CIK
        except Exception:
            return _TICKER_TO_CIK  # 실패하면 기존 맵 (있으면)


def _get_cik(ticker: str) -> Optional[str]:
    """티커 → 10자리 CIK. 없으면 None."""
    t = _normalize_ticker(ticker)
    if not t:
        return None
    m = _load_ticker_map()
    return m.get(t)


# us-gaap XBRL 태그 후보 (회사마다 사용 태그 다름 — 우선순위 순서로 시도)
_FIELD_CONCEPTS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "cost_of_revenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "rd_expense": ["ResearchAndDevelopmentExpense"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "total_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "operating_cf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "shares_outstanding": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ],
    "eps_basic": ["EarningsPerShareBasic"],
    "eps_diluted": ["EarningsPerShareDiluted"],
}


def _fetch_company_facts(cik: str) -> Optional[dict]:
    """SEC companyfacts JSON — 한 회사의 모든 XBRL 데이터를 한 번에.

    주의: 응답 1~5MB라 메모리 캐시 X (메모리 폭주 방지).
    fetch_financials가 즉시 파싱·작은 결과만 24h 캐시함.
    음성(실패)만 1시간 캐시 — 재호출 폭주 차단.
    """
    neg_key = f"sec_facts_fail:{cik}"
    if cache.get(neg_key):
        return None

    try:
        _throttle()
        r = requests.get(
            f"{SEC_FACTS_BASE}/CIK{cik}.json",
            headers=_headers(),
            timeout=20,
        )
        if r.status_code != 200:
            cache.set(neg_key, True, ttl=3600)  # 실패만 1시간 캐시
            return None
        # 원본 JSON은 캐시하지 않고 즉시 반환 (호출자가 파싱 후 폐기)
        return r.json()
    except Exception:
        cache.set(neg_key, True, ttl=3600)
        return None


def _extract_annual_series(facts: dict, concept: str) -> dict[int, float]:
    """concept의 연간(10-K FY) 시계열 추출 — report end date 기준.

    핵심: 회계연도(fy) 라벨이 아닌 **end date의 캘린더 연도**로 매핑.
    NVDA처럼 1월 종료 기업 정상 처리 (FY2025 end=2025-01-26 → year=2025).

    동일 연도에 여러 filing(원공시 + 정정 10-K/A)이 있으면 가장 최근 filed 우선.

    Returns:
        {year: value} — year는 end date의 연도, 누락 가능.
    """
    try:
        node = facts.get("facts", {}).get("us-gaap", {}).get(concept)
        if not node:
            return {}
        units = node.get("units", {})
        unit_keys = list(units.keys())
        if not unit_keys:
            return {}
        primary = "USD" if "USD" in unit_keys else unit_keys[0]
        entries = units.get(primary, [])

        # 10-K 또는 10-K/A에서 fp=FY인 항목만
        rows = []
        for e in entries:
            if e.get("fp") != "FY":
                continue
            form = (e.get("form") or "")
            if not form.startswith("10-K"):
                continue
            end = e.get("end")
            val = e.get("val")
            filed = e.get("filed") or ""
            if not end or val is None:
                continue
            try:
                year = int(end[:4])
                rows.append((year, end, filed, float(val)))
            except (ValueError, TypeError):
                continue
        if not rows:
            return {}

        # 같은 연도 + 같은 end 내에서는 filed가 가장 최근 것 (정정 공시 우선)
        # 같은 연도 다른 end도 있을 수 있는데, 그땐 더 최근 end 우선
        rows.sort(key=lambda r: (r[1], r[2]), reverse=True)
        seen: dict[int, float] = {}
        for year, end, filed, val in rows:
            if year not in seen:
                seen[year] = val
        return seen
    except Exception:
        return {}


def _pick_concept_series(facts: dict, concept_list: list[str], pick: str = "max") -> dict[int, float]:
    """후보 concept들의 시계열을 합침 — 회사·시기별 태그 변경 대응.

    회계 표준 진화로 같은 회사가 시기마다 다른 태그 사용:
        - 2010년대 초반: SalesRevenueNet (구 us-gaap)
        - 중반: Revenues (브릿지)
        - 2018+: RevenueFromContractWithCustomerExcludingAssessedTax (ASC 606)

    같은 연도에 여러 컨셉트가 값을 주면:
        - pick="max": 가장 큰 값 (revenue·자산처럼 부분값 vs 연간합계 충돌 시 안전)
        - pick="first": concept_list 순서 우선 (eps처럼 max가 의미 없는 경우)
    """
    by_year: dict[int, list[float]] = {}
    for c in concept_list:
        s = _extract_annual_series(facts, c)
        for y, v in s.items():
            by_year.setdefault(y, []).append(v)

    if pick == "first":
        # 첫 번째로 들어온 값
        return {y: vals[0] for y, vals in by_year.items()}
    # default: 가장 큰 값 (분기 일부 vs 연간 합계 충돌 시 안전)
    return {y: max(vals) for y, vals in by_year.items()}


def fetch_financials(ticker: str, years: int = 5) -> Optional[dict]:
    """SEC EDGAR에서 최근 N년 연간 연결재무제표 조회.

    DART 클라이언트와 동일 인터페이스 — app.py가 같은 패턴으로 병합 가능.

    Returns:
        {years, revenue, net_income, operating_income, gross_profit,
         rd_expense, equity, total_assets, total_liabilities,
         current_assets, current_liabilities, operating_cf, capex, fcf, source}
        실패/비대상이면 None.
    """
    cik = _get_cik(ticker)
    if not cik:
        return None

    # v2: end-date 기반 매핑 (v1 캐시 무효화 — NVDA 등 비표준 회계연도 버그 수정)
    cache_key = f"sec_fin_v2:{cik}:{years}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit if hit else None

    facts = _fetch_company_facts(cik)
    if not facts:
        cache.set(cache_key, False, ttl=3600)
        return None

    # 1단계: 각 필드별로 end-date 기반 시계열 수집
    # EPS는 max가 무의미 (희석/기본 차이만 있음) → first 우선
    _PICK_FIRST = {"eps_basic", "eps_diluted", "shares_outstanding"}
    series_by_field: dict[str, dict[int, float]] = {}
    all_years: set[int] = set()
    for field, concepts in _FIELD_CONCEPTS.items():
        pick = "first" if field in _PICK_FIRST else "max"
        s = _pick_concept_series(facts, concepts, pick=pick)
        series_by_field[field] = s
        all_years.update(s.keys())

    if not all_years:
        cache.set(cache_key, False, ttl=3600)
        return None

    # 2단계: 매출 또는 순이익이 있는 연도만 유효
    rev_series = series_by_field.get("revenue", {})
    ni_series = series_by_field.get("net_income", {})
    valid_years = sorted(y for y in all_years if y in rev_series or y in ni_series)
    if not valid_years:
        cache.set(cache_key, False, ttl=3600)
        return None

    # 3단계: 가장 최근 N년
    valid_years = valid_years[-years:]

    by_year: dict[int, dict[str, float]] = {}
    for y in valid_years:
        year_data = {}
        for field, s in series_by_field.items():
            if y in s:
                year_data[field] = s[y]
        by_year[y] = year_data

    sorted_years = valid_years

    def col(field):
        return [by_year[y].get(field) for y in sorted_years]

    # gross_profit fallback: 없으면 revenue - cost_of_revenue
    gp_col = col("gross_profit")
    if all(v is None for v in gp_col):
        gp_col = []
        for y in sorted_years:
            d = by_year[y]
            r, c = d.get("revenue"), d.get("cost_of_revenue")
            gp_col.append(r - c if (r is not None and c is not None) else None)

    # FCF 계산: operating_cf - capex (SEC capex는 양수로 들어옴, 지출이라 빼기)
    fcf_col = []
    for y in sorted_years:
        d = by_year[y]
        ocf, cx = d.get("operating_cf"), d.get("capex")
        if ocf is None:
            fcf_col.append(None)
        else:
            fcf_col.append(ocf - (cx or 0))

    result = {
        "years": [str(y) for y in sorted_years],
        "revenue": col("revenue"),
        "net_income": col("net_income"),
        "operating_income": col("operating_income"),
        "gross_profit": gp_col,
        "rd_expense": col("rd_expense"),
        "equity": col("total_equity"),
        "total_assets": col("total_assets"),
        "total_liabilities": col("total_liabilities"),
        "current_assets": col("current_assets"),
        "current_liabilities": col("current_liabilities"),
        "operating_cf": col("operating_cf"),
        "capex": col("capex"),
        "fcf": fcf_col,
        "shares_outstanding": col("shares_outstanding"),
        "eps_diluted": col("eps_diluted"),
        "eps_basic": col("eps_basic"),
        "source": "sec_edgar",
    }
    # 명시적 메모리 해제 — 원본 facts(1~5MB) 폐기
    facts = None
    by_year = None
    cache.set(cache_key, result, ttl=24 * 3600)
    return result


def fetch_company_meta(ticker: str) -> Optional[dict]:
    """회사 메타 정보 (이름·sector 등) — companyfacts에서 추출."""
    cik = _get_cik(ticker)
    if not cik:
        return None
    facts = _fetch_company_facts(cik)
    if not facts:
        return None
    return {
        "cik": cik,
        "entity_name": facts.get("entityName"),
    }
