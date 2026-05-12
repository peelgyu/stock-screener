"""베타(시장 변동성) 자체 계산 — yfinance.beta 의존 제거.

한국 종목: KOSPI(^KS11) 대비 5년 주봉 수익률 회귀
미국 종목: 기본 yfinance.beta 사용 (백업으로 SP500 회귀 가능)

베타 = Cov(종목 수익률, 시장 수익률) / Var(시장 수익률)
24h 캐시.
"""
from __future__ import annotations

import logging
from typing import Optional

from .cache import cache

logger = logging.getLogger(__name__)

try:
    import FinanceDataReader as fdr  # type: ignore
    _FDR = True
except Exception:
    fdr = None
    _FDR = False


def _is_kr(ticker: str) -> bool:
    t = (ticker or "").upper()
    return t.endswith(".KS") or t.endswith(".KQ")


def calc_kr_beta(ticker: str, years: int = 5) -> Optional[float]:
    """한국 종목 베타 — KOSPI(^KS11) 대비 주봉 수익률 회귀.

    Returns:
        베타 값 (보통 0.3~2.5). 데이터 부족 시 None.
    """
    if not _FDR or not _is_kr(ticker):
        return None

    cache_key = f"beta_kr:{ticker}:{years}"
    hit = cache.get(cache_key)
    if hit is not None:
        return float(hit) if hit != "none" else None

    code = ticker.split(".")[0]

    try:
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=int(years * 365.25))
        start_str = start.strftime("%Y-%m-%d")

        # 종목 가격
        df_stock = fdr.DataReader(code, start=start_str)
        if df_stock is None or df_stock.empty or len(df_stock) < 60:
            cache.set(cache_key, "none", 3600)
            return None

        # KOSPI 지수 (벤치마크)
        df_idx = fdr.DataReader("KS11", start=start_str)
        if df_idx is None or df_idx.empty:
            cache.set(cache_key, "none", 3600)
            return None

        # 주봉으로 리샘플 (월요일 종가 기준)
        s = df_stock["Close"].resample("W-MON").last().dropna()
        m = df_idx["Close"].resample("W-MON").last().dropna()
        # 공통 기간
        common = s.index.intersection(m.index)
        if len(common) < 30:
            cache.set(cache_key, "none", 3600)
            return None
        s = s.loc[common]
        m = m.loc[common]

        # 주봉 수익률
        s_ret = s.pct_change().dropna()
        m_ret = m.pct_change().dropna()
        common = s_ret.index.intersection(m_ret.index)
        if len(common) < 30:
            cache.set(cache_key, "none", 3600)
            return None
        s_ret = s_ret.loc[common]
        m_ret = m_ret.loc[common]

        # 베타 = Cov(s, m) / Var(m)
        var_m = float(m_ret.var())
        if var_m <= 0:
            cache.set(cache_key, "none", 3600)
            return None
        cov_sm = float(((s_ret - s_ret.mean()) * (m_ret - m_ret.mean())).mean())
        beta = cov_sm / var_m

        # 합리적 범위 (0.1 ~ 3.5) 클램프
        if beta < 0.1 or beta > 3.5:
            beta = max(0.3, min(2.5, beta))

        cache.set(cache_key, beta, 24 * 3600)
        return float(beta)
    except Exception as e:
        logger.warning("KR beta calc failed for %s: %s", ticker, e)
        cache.set(cache_key, "none", 3600)
        return None
