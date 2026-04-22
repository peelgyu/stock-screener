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


def fetch_financials(ticker: str, years: int = 5) -> Optional[dict]:
    """DART에서 최근 N년 연간 연결재무제표 조회.

    Returns:
        {
            "years": ["2020", "2021", ..., "2024"],  # oldest → newest
            "revenue": [...],
            "net_income": [...],
            "equity": [...],       # 자본총계
            "source": "dart",
        }
        실패/비대상이면 None.
    """
    key = _api_key()
    if not key:
        return None

    corp = _corp_code(ticker)
    if not corp:
        return None

    cache_key = f"dart_fin:{corp}:{years}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    # 연도 리스트: 올해-1부터 과거 N년. 올해분은 annual 보고서가 아직 없을 수 있음.
    import datetime
    now_year = datetime.datetime.now().year
    year_list = list(range(now_year - 1, now_year - 1 - years, -1))

    rev: dict[str, float] = {}
    ni: dict[str, float] = {}
    eq: dict[str, float] = {}

    for y in year_list:
        for fs_div in ("CFS", "OFS"):  # CFS=연결, OFS=별도. 연결 우선.
            try:
                r = requests.get(
                    f"{DART_BASE}/fnlttSinglAcntAll.json",
                    params={
                        "crtfc_key": key,
                        "corp_code": corp,
                        "bsns_year": str(y),
                        "reprt_code": "11011",  # 사업보고서 (연간)
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

            got_rev = got_ni = got_eq = False
            for row in rows:
                nm = (row.get("account_nm") or "").strip()
                sj = row.get("sj_div") or ""  # BS/IS/CIS/CF
                amt = _fnum(row.get("thstrm_amount"))
                if amt is None:
                    continue

                # 매출액 (IS 또는 CIS)
                if not got_rev and sj in ("IS", "CIS") and nm in ("매출액", "영업수익", "수익(매출액)"):
                    rev[str(y)] = amt
                    got_rev = True
                # 당기순이익 (IS 또는 CIS)
                if not got_ni and sj in ("IS", "CIS") and nm in ("당기순이익", "당기순이익(손실)", "연결당기순이익"):
                    ni[str(y)] = amt
                    got_ni = True
                # 자본총계 (BS)
                if not got_eq and sj == "BS" and nm in ("자본총계", "자본 총계"):
                    eq[str(y)] = amt
                    got_eq = True

            if got_rev or got_ni:
                break  # 연결(CFS)에서 찾았으면 별도(OFS) 스킵

    if not rev and not ni:
        return None

    sorted_years = sorted(set(list(rev.keys()) + list(ni.keys()) + list(eq.keys())))
    result = {
        "years": sorted_years,
        "revenue": [rev.get(y) for y in sorted_years],
        "net_income": [ni.get(y) for y in sorted_years],
        "equity": [eq.get(y) for y in sorted_years],
        "source": "dart",
    }
    cache.set(cache_key, result, ttl=24 * 3600)  # 하루 캐시
    return result


def is_available() -> bool:
    return bool(_api_key())
