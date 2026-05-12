"""일일 금융 브리핑 — 매일 오전 KST 자동 생성.

데이터 소스:
- 미국 지수: yfinance (^GSPC·^IXIC·^DJI)
- 한국 지수: FDR (^KS11·^KQ11)
- 환율: yfinance USD/KRW
- 공포탐욕지수: 자체 계산 (analysis/fear_greed)
- 거래량 TOP: 자체 (analysis/most_active)
- 시장 뉴스: 네이버 뉴스 검색 + 투자 시그널 필터

캐싱: 일자별 1개 결과 → static/briefings/YYYY-MM-DD.json 저장 (중복 호출 비용 0)
"""
from __future__ import annotations

import os
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Optional

import yfinance as yf

try:
    import FinanceDataReader as fdr
    FDR_OK = True
except Exception:
    FDR_OK = False

from .cache import cache


_BRIEFING_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "briefings")


def _kst_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=9)))


def _today_kst_str() -> str:
    return _kst_now().strftime("%Y-%m-%d")


# 매일 아침 KST 08:30 — "전날 시황" 갱신 기준 시각
# 이 시각 이전에는 그저께 시황을, 이후에는 어제 시황을 표시
# (미국 시장은 한국 새벽 5~6시 마감, 한국 시장은 어제 15:30 마감)
BRIEFING_CUTOFF_HOUR = 8
BRIEFING_CUTOFF_MIN = 30


def _briefing_target_date() -> str:
    """현재 시점에 표시해야 할 브리핑 날짜 — '전날 시황' 갱신 기준.

    매일 KST 08:30이 갱신 컷오프:
    - 08:30 이전: 그저께 날짜 반환 (가장 최근 마감일이 그저께)
    - 08:30 이후: 어제 날짜 반환 (어제 마감 데이터 표시)

    예: 2026-05-05 09:00 KST → "2026-05-04" (어제 시황)
        2026-05-05 07:00 KST → "2026-05-03" (그저께 시황)
    """
    now = _kst_now()
    cutoff = now.replace(hour=BRIEFING_CUTOFF_HOUR, minute=BRIEFING_CUTOFF_MIN, second=0, microsecond=0)
    if now < cutoff:
        target = now - timedelta(days=2)
    else:
        target = now - timedelta(days=1)
    return target.strftime("%Y-%m-%d")


def _fetch_index(symbol: str) -> Optional[dict]:
    """지수 시세 + 변동률. yfinance Ticker.history 마지막 2일 비교."""
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="5d")
        if hist is None or len(hist) < 2:
            return None
        last = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])
        chg = last - prev
        chg_pct = (chg / prev * 100) if prev else 0
        return {
            "symbol": symbol,
            "value": round(last, 2),
            "change": round(chg, 2),
            "change_pct": round(chg_pct, 2),
        }
    except Exception:
        return None


def _fetch_kr_index_fdr(code: str) -> Optional[dict]:
    """한국 지수 (KS11·KQ11) — FDR 전용."""
    if not FDR_OK:
        return None
    try:
        df = fdr.DataReader(code, start=(_kst_now() - timedelta(days=10)).strftime("%Y-%m-%d"))
        if df is None or len(df) < 2:
            return None
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        chg = last - prev
        chg_pct = (chg / prev * 100) if prev else 0
        return {
            "symbol": code,
            "value": round(last, 2),
            "change": round(chg, 2),
            "change_pct": round(chg_pct, 2),
        }
    except Exception:
        return None


def _fetch_fx_usd_krw() -> Optional[dict]:
    """USD/KRW 환율 + 기준 시각."""
    try:
        from .fx import get_usd_krw_meta
        meta = get_usd_krw_meta()
        return {
            "usd_krw": meta.get("rate"),
            "fetched_at": meta.get("fetched_at"),
            "source": meta.get("source"),
        }
    except Exception:
        return None


def _fetch_market_news(query: str, count: int = 5) -> list:
    """네이버 뉴스 검색 — 투자 시그널 필터 거친 결과."""
    try:
        from . import naver_news
        if not naver_news.is_available():
            return []
        items = naver_news.fetch_news(query, display=count, sort="date") or []
        return items[:count]
    except Exception:
        return []


def _fetch_top_movers_us(count: int = 5) -> dict:
    """미국 상승·하락 TOP."""
    try:
        from analysis.most_active import get_most_active_us
        active = get_most_active_us(count=20) or []
        # changePercent 기준 상승·하락 정렬
        sorted_up = sorted([x for x in active if x.get("changePercent") is not None],
                          key=lambda x: x["changePercent"], reverse=True)
        sorted_down = sorted([x for x in active if x.get("changePercent") is not None],
                            key=lambda x: x["changePercent"])
        return {
            "gainers": sorted_up[:count],
            "losers":  sorted_down[:count],
        }
    except Exception:
        return {"gainers": [], "losers": []}


def _fetch_top_movers_kr(count: int = 5) -> dict:
    """한국 상승·하락 TOP — FDR."""
    if not FDR_OK:
        return {"gainers": [], "losers": []}
    try:
        # 코스피·코스닥 거래량 상위 + 등락률 정렬
        from analysis.most_active import get_most_active_kr
        active = get_most_active_kr(count=20) or []
        sorted_up = sorted([x for x in active if x.get("changePercent") is not None],
                          key=lambda x: x["changePercent"], reverse=True)
        sorted_down = sorted([x for x in active if x.get("changePercent") is not None],
                            key=lambda x: x["changePercent"])
        return {
            "gainers": sorted_up[:count],
            "losers":  sorted_down[:count],
        }
    except Exception:
        return {"gainers": [], "losers": []}


def _fetch_fear_greed() -> Optional[dict]:
    """공포탐욕지수 — 이미 시스템에 있는 것 재사용."""
    try:
        from analysis.fear_greed import calculate_fear_greed
        result = calculate_fear_greed()
        if result and result.get("available"):
            return {
                "score": result.get("score"),
                "label": result.get("label"),
                "level": result.get("level"),
            }
    except Exception:
        pass
    return None


def generate_briefing(date_str: Optional[str] = None) -> dict:
    """일일 브리핑 데이터 생성 — 전날 마감 시황 기준.

    Args:
        date_str: "YYYY-MM-DD" 또는 None (자동 — 전날 시황 날짜)

    Returns:
        브리핑 데이터 dict (저장·렌더링용)
    """
    date_str = date_str or _briefing_target_date()
    now = _kst_now()

    # 11개 외부 API 호출을 병렬화 — 순차 30~60초 → 병렬 5~10초
    # 각 호출은 내부에서 이미 try/except로 감싸져 None/{} 반환하므로 future.result()도 안전
    with ThreadPoolExecutor(max_workers=11, thread_name_prefix="briefing") as ex:
        futures = {
            "sp500":  ex.submit(_fetch_index, "^GSPC"),
            "nasdaq": ex.submit(_fetch_index, "^IXIC"),
            "dow":    ex.submit(_fetch_index, "^DJI"),
            "kospi":  ex.submit(_fetch_kr_index_fdr, "KS11"),
            "kosdaq": ex.submit(_fetch_kr_index_fdr, "KQ11"),
            "fx":     ex.submit(_fetch_fx_usd_krw),
            "fg":     ex.submit(_fetch_fear_greed),
            "us_mov": ex.submit(_fetch_top_movers_us, count=5),
            "kr_mov": ex.submit(_fetch_top_movers_kr, count=5),
            "us_news": ex.submit(_fetch_market_news, "미국 증시", count=6),
            "kr_news": ex.submit(_fetch_market_news, "코스피", count=6),
        }
        # 각 future가 내부에서 예외 안 던지도록 짜여 있음 — 안전망으로 한 번 더 감쌈
        results = {}
        for k, f in futures.items():
            try:
                results[k] = f.result(timeout=30)
            except Exception:
                results[k] = None

    return {
        "date": date_str,
        "generated_at_kst": now.strftime("%Y-%m-%d %H:%M KST"),
        "weekday_kr": ["월", "화", "수", "목", "금", "토", "일"][now.weekday()],
        "us_indices": {
            "sp500":  results["sp500"],
            "nasdaq": results["nasdaq"],
            "dow":    results["dow"],
        },
        "kr_indices": {
            "kospi":  results["kospi"],
            "kosdaq": results["kosdaq"],
        },
        "fx": results["fx"] or {"usd_krw": None, "fetched_at": None, "source": None},
        "fear_greed": results["fg"],
        "top_movers_us": results["us_mov"],
        "top_movers_kr": results["kr_mov"],
        "news_us": results["us_news"],
        "news_kr": results["kr_news"],
        "data_sources": {
            "indices": "yfinance · FinanceDataReader (KRX)",
            "news": "네이버 검색 API (투자 시그널 필터)",
            "fx": "yfinance",
            "fear_greed": "StockInto 자체 계산 (6지표 가중평균)",
        },
        "disclaimer": "본 브리핑은 정보 제공 목적이며, 투자 자문이 아닙니다. "
                      "투자 판단과 그 결과의 책임은 이용자 본인에게 있습니다.",
    }


def save_briefing(briefing: dict) -> str:
    """브리핑을 static/briefings/YYYY-MM-DD.json에 저장."""
    os.makedirs(_BRIEFING_DIR, exist_ok=True)
    date_str = briefing.get("date") or _briefing_target_date()
    path = os.path.join(_BRIEFING_DIR, f"{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=2)
    return path


def load_briefing(date_str: Optional[str] = None) -> Optional[dict]:
    """저장된 브리핑 로드. 없으면 None."""
    date_str = date_str or _briefing_target_date()
    path = os.path.join(_BRIEFING_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_or_generate(date_str: Optional[str] = None) -> dict:
    """전날 시황 브리핑 로드/생성. 08:30 KST 갱신 기준.

    date_str 없으면 자동으로 _briefing_target_date() 사용 (전날).
    target_date 외 다른 날짜는 아카이브 — 파일에 있으면 반환, 없으면 빈 dict.
    """
    target = _briefing_target_date()
    date_str = date_str or target

    # 가장 최근 갱신 대상 날짜는 cache 우선
    if date_str == target:
        cached = cache.get(f"daily_briefing:{date_str}")
        if cached:
            return cached
        existing = load_briefing(date_str)
        if existing:
            cache.set(f"daily_briefing:{date_str}", existing, ttl=3600)
            return existing
        # 신규 생성
        briefing = generate_briefing(date_str)
        save_briefing(briefing)
        cache.set(f"daily_briefing:{date_str}", briefing, ttl=3600)
        return briefing

    # 과거 날짜는 파일만
    return load_briefing(date_str) or {}


def list_archives(limit: int = 30) -> list:
    """저장된 브리핑 날짜 목록 (최신순)."""
    if not os.path.isdir(_BRIEFING_DIR):
        return []
    files = [f for f in os.listdir(_BRIEFING_DIR) if f.endswith(".json")]
    files.sort(reverse=True)
    return [f.replace(".json", "") for f in files[:limit]]
