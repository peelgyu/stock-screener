"""환율 fetch — USD/KRW 환산 등.

yfinance에서 환율 받기 (USDKRW=X 페어). 4시간 캐시 + 폴백값.
실패 시에도 안전한 추정치 반환해서 앱은 동작 유지.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from .cache import cache


# 폴백 환율 (yfinance 실패 시 사용 — 운영 중 1년에 1번 정도 갱신)
_FALLBACK_USD_KRW = 1380.0

_FX_CACHE_KEY = "fx_usd_krw_v2"  # v2: 메타 포함 dict 구조
_FX_TTL = 4 * 3600  # 4시간 — yfinance 부하·환율 신선도 균형
_FX_FALLBACK_TTL = 1 * 3600  # 폴백은 1시간만 (재시도 기회 확보)
_FX_LOCK = threading.Lock()

_KST = timezone(timedelta(hours=9))


def _now_kst_str() -> str:
    return datetime.now(_KST).strftime("%Y-%m-%d %H:%M KST")


def get_usd_krw_meta() -> dict:
    """USD → KRW 환율 + 기준 시각 메타.

    Returns:
        {"rate": float, "fetched_at": "YYYY-MM-DD HH:MM KST", "source": "yfinance"|"fallback"}
    """
    cached = cache.get(_FX_CACHE_KEY)
    if isinstance(cached, dict) and "rate" in cached:
        return cached

    with _FX_LOCK:
        # double-check after lock
        cached = cache.get(_FX_CACHE_KEY)
        if isinstance(cached, dict) and "rate" in cached:
            return cached

        try:
            import yfinance as yf
            t = yf.Ticker("USDKRW=X")
            # fast_info 우선 (가벼움), 없으면 history 마지막 값
            fast = getattr(t, "fast_info", None)
            rate = None
            if fast is not None:
                rate = getattr(fast, "last_price", None) or fast.get("lastPrice") if hasattr(fast, "get") else None
            if rate is None:
                hist = t.history(period="5d", interval="1d")
                if hist is not None and not hist.empty:
                    rate = float(hist["Close"].iloc[-1])
            if rate and 800 < rate < 2500:  # 합리적 범위 검증
                meta = {
                    "rate": float(rate),
                    "fetched_at": _now_kst_str(),
                    "source": "yfinance",
                }
                cache.set(_FX_CACHE_KEY, meta, _FX_TTL)
                return meta
        except Exception:
            pass

        # 폴백
        meta = {
            "rate": _FALLBACK_USD_KRW,
            "fetched_at": _now_kst_str(),
            "source": "fallback",
        }
        cache.set(_FX_CACHE_KEY, meta, _FX_FALLBACK_TTL)
        return meta


def get_usd_krw() -> float:
    """USD → KRW 환율(rate)만 반환 — 시총 환산 등 단순 호출용 (하위 호환)."""
    return float(get_usd_krw_meta()["rate"])
