"""환율 fetch — USD/KRW 환산 등.

yfinance에서 환율 받기 (USDKRW=X 페어). 24시간 캐시 + 폴백값.
실패 시에도 안전한 추정치 반환해서 앱은 동작 유지.
"""
from __future__ import annotations

import threading

from .cache import cache


# 폴백 환율 (yfinance 실패 시 사용 — 운영 중 1년에 1번 정도 갱신)
_FALLBACK_USD_KRW = 1380.0

_FX_CACHE_KEY = "fx_usd_krw_v1"
_FX_TTL = 24 * 3600  # 24시간
_FX_LOCK = threading.Lock()


def get_usd_krw() -> float:
    """USD → KRW 환율. 24h 캐시 + 폴백 1380."""
    cached = cache.get(_FX_CACHE_KEY)
    if cached is not None:
        try:
            return float(cached)
        except (TypeError, ValueError):
            pass

    with _FX_LOCK:
        # double-check after lock
        cached = cache.get(_FX_CACHE_KEY)
        if cached is not None:
            try:
                return float(cached)
            except (TypeError, ValueError):
                pass

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
                cache.set(_FX_CACHE_KEY, float(rate), _FX_TTL)
                return float(rate)
        except Exception:
            pass

        # 폴백
        cache.set(_FX_CACHE_KEY, _FALLBACK_USD_KRW, 3600)  # 1h만 유지 (재시도 기회)
        return _FALLBACK_USD_KRW
