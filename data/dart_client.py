"""DART OpenAPI 클라이언트 — 한국 주식 공시 재무제표 조회.

근거: 금융감독원 전자공시시스템(https://opendart.fss.or.kr)
라이선스: 공공누리 제1유형 (출처표시만 하면 상업적 이용 가능)
호출 한도: 일 20,000회 / 분 100회

yfinance보다 한국 기업 데이터가 훨씬 정확하므로 .KS/.KQ 티커에 우선 적용.
"""
from __future__ import annotations

import io
import os
import re
import time
import zipfile
import threading
import xml.etree.ElementTree as ET
from typing import Optional

import requests

from .cache import cache


DART_BASE = "https://opendart.fss.or.kr/api"
_CORP_MAP: dict[str, str] = {}  # stock_code(6자리) → corp_code(8자리)
_CORP_LOCK = threading.Lock()
_CORP_LOADED_AT: float = 0.0
_CORP_TTL = 7 * 24 * 3600  # 7일


def _api_key() -> Optional[str]:
    return os.getenv("DART_API_KEY")


def _stock_code(ticker: str) -> Optional[str]:
    """'005930.KS' → '005930'. 숫자 6자리가 아니면 None."""
    code = (ticker or "").split(".")[0]
    return code if re.fullmatch(r"\d{6}", code) else None


def _load_corp_map() -> dict[str, str]:
    """DART 기업코드 전체 목록(zip) 받아서 stock_code → corp_code 맵 구성.

    호출: corpCode.xml 전체를 zip으로 내려받음 (주 1회 정도면 충분).
    캐시: 메모리 + 7일 TTL.
    """
    global _CORP_LOADED_AT
    with _CORP_LOCK:
        if _CORP_MAP and (time.time() - _CORP_LOADED_AT) < _CORP_TTL:
            return _CORP_MAP

        key = _api_key()
        if not key:
            return {}

        try:
            r = requests.get(
                f"{DART_BASE}/corpCode.xml",
                params={"crtfc_key": key},
                timeout=15,
            )
            r.raise_for_status()
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            xml_bytes = zf.read(zf.namelist()[0])
            root = ET.fromstring(xml_bytes)

            new_map: dict[str, str] = {}
            for node in root.iter("list"):
                stock = (node.findtext("stock_code") or "").strip()
                corp = (node.findtext("corp_code") or "").strip()
                if stock and corp and re.fullmatch(r"\d{6}", stock):
                    new_map[stock] = corp
            _CORP_MAP.clear()
            _CORP_MAP.update(new_map)
            _CORP_LOADED_AT = time.time()
            return _CORP_MAP
        except Exception:
            return _CORP_MAP  # 실패하면 기존 맵 반환 (있으면)


def _corp_code(ticker: str) -> Optional[str]:
    sc = _stock_code(ticker)
    if not sc:
        return None
    m = _load_corp_map()
    return m.get(sc)


def _fnum(v) -> Optional[float]:
    """DART가 주는 문자열 숫자를 float으로. 빈 값/부호 처리."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except Exception:
        return None


# 계정과목 별칭 맵 — DART 회사마다 표기가 살짝 다름
ACCOUNT_ALIASES = {
    "revenue": ("IS", "CIS", ["매출액", "영업수익", "수익(매출액)", "매출", "수익"]),
    "cost_of_revenue": ("IS", "CIS", ["매출원가"]),
    "gross_profit": ("IS", "CIS", ["매출총이익", "매출총이익(손실)"]),
    "operating_income": ("IS", "CIS", ["영업이익", "영업이익(손실)"]),
    "rd_expense": ("IS", "CIS", ["연구개발비", "경상연구개발비"]),
    "net_income": ("IS", "CIS", ["당기순이익", "당기순이익(손실)", "연결당기순이익", "반기순이익"]),
    "total_assets": ("BS", None, ["자산총계", "자산 총계"]),
    "total_liabilities": ("BS", None, ["부채총계", "부채 총계"]),
    "total_equity": ("BS", None, ["자본총계", "자본 총계"]),
    "current_assets": ("BS", None, ["유동자산"]),
    "current_liabilities": ("BS", None, ["유동부채"]),
    "operating_cf": ("CF", None, ["영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동 현금흐름", "영업활동으로 인한 현금흐름"]),
    "capex": ("CF", None, ["유형자산의 취득", "유형자산의취득", "유형자산취득"]),
}


def _extract_row(row, target_sj, target_sj2, target_names):
    nm = (row.get("account_nm") or "").strip()
    sj = row.get("sj_div") or ""
    if sj != target_sj and (target_sj2 is None or sj != target_sj2):
        return None
    for name in target_names:
        if nm == name:
            return _fnum(row.get("thstrm_amount"))
    return None


def fetch_financials(ticker: str, years: int = 5) -> Optional[dict]:
    """DART에서 최근 N년 연간 연결재무제표 조회.

    Returns:
        연도별 dict 리스트. 각 항목은 revenue·net_income·operating_income·total_assets 등 모두 포함.
        실패/비대상이면 None.
    """
    key = _api_key()
    if not key:
        return None

    corp = _corp_code(ticker)
    if not corp:
        return None

    cache_key = f"dart_fin_v2:{corp}:{years}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    import datetime
    now_year = datetime.datetime.now().year
    year_list = list(range(now_year - 1, now_year - 1 - years, -1))

    # {year: {field: value}}
    by_year: dict[str, dict[str, float]] = {}

    for y in year_list:
        for fs_div in ("CFS", "OFS"):
            try:
                r = requests.get(
                    f"{DART_BASE}/fnlttSinglAcntAll.json",
                    params={
                        "crtfc_key": key,
                        "corp_code": corp,
                        "bsns_year": str(y),
                        "reprt_code": "11011",
                        "fs_div": fs_div,
                    },
                    timeout=10,
                )
                if r.status_code != 200:
                    continue
                data = r.json()
                if data.get("status") != "000":
                    continue
                rows = data.get("list") or []
            except Exception:
                continue

            year_data: dict[str, float] = {}
            for row in rows:
                for field, (sj1, sj2, names) in ACCOUNT_ALIASES.items():
                    if field in year_data:
                        continue
                    v = _extract_row(row, sj1, sj2, names)
                    if v is not None:
                        year_data[field] = v

            if year_data.get("revenue") is not None or year_data.get("net_income") is not None:
                by_year[str(y)] = year_data
                break  # 연결 성공 시 별도 스킵

    if not by_year:
        return None

    sorted_years = sorted(by_year.keys())

    def col(field):
        return [by_year[y].get(field) for y in sorted_years]

    # gross_profit 계산 fallback: 없으면 revenue - cost_of_revenue
    gp_col = col("gross_profit")
    if all(v is None for v in gp_col):
        gp_col = []
        for y in sorted_years:
            d = by_year[y]
            r, c = d.get("revenue"), d.get("cost_of_revenue")
            gp_col.append(r - c if (r is not None and c is not None) else None)

    # FCF 계산: operating_cf + capex (DART capex는 이미 음수로 들어옴)
    fcf_col = []
    for y in sorted_years:
        d = by_year[y]
        ocf, cx = d.get("operating_cf"), d.get("capex")
        if ocf is None:
            fcf_col.append(None)
        else:
            fcf_col.append(ocf + (cx or 0) if cx is not None and cx < 0 else ocf - (cx or 0))

    result = {
        "years": sorted_years,
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
        "source": "dart",
    }
    cache.set(cache_key, result, ttl=24 * 3600)
    return result


def is_available() -> bool:
    return bool(_api_key())
