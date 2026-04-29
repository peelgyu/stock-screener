"""KRX(한국거래소) 데이터 클라이언트 — 외국인·기관·개인 매매 동향, 보유율, 공매도 잔고.

근거: 한국거래소 정보데이터시스템(http://data.krx.co.kr) 공개 데이터
래퍼: pykrx (https://github.com/sharebook-kr/pykrx) — KRX 페이지를 파싱
대상: 한국 종목(.KS / .KQ)에만 적용
호출 비용: 무료, 무제한 (단 페이지 부하 고려해 캐싱)

DART와 보완 관계:
- DART → 재무제표·공시 (분기/연간)
- KRX → 외국인 보유율, 일별 매매 동향, 공매도 (일별)
"""
from __future__ import annotations

import re
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from .cache import cache

# pykrx는 외부 네트워크 호출이 잦고 가끔 KRX 응답 변경에 깨질 수 있으므로 보수적으로 import
try:
    from pykrx import stock as _krx_stock  # type: ignore
    _KRX_AVAILABLE = True
except Exception:  # pragma: no cover - 환경에 따라 import 실패 가능
    _krx_stock = None
    _KRX_AVAILABLE = False


_CACHE_TTL = 24 * 3600  # 일별 데이터라 24시간 캐시 충분
_RATE_LIMIT_LOCK = threading.Lock()
_LAST_CALL = 0.0
_MIN_INTERVAL = 0.15  # 200ms 이내 연속 호출 방지 (KRX 부하 완화)


def is_available() -> bool:
    return _KRX_AVAILABLE


def _stock_code(ticker: str) -> Optional[str]:
    """'005930.KS' → '005930'. 6자리 숫자가 아니면 None."""
    if not ticker:
        return None
    code = ticker.split(".")[0]
    return code if re.fullmatch(r"\d{6}", code) else None


def _kst_today() -> str:
    """한국 시간 기준 오늘 yyyymmdd. 장마감 후(15:30~) 데이터가 안정적으로 갱신됨."""
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y%m%d")


def _kst_days_ago(n: int) -> str:
    kst = timezone(timedelta(hours=9))
    return (datetime.now(kst) - timedelta(days=n)).strftime("%Y%m%d")


def _throttle():
    global _LAST_CALL
    with _RATE_LIMIT_LOCK:
        now = time.time()
        wait = _MIN_INTERVAL - (now - _LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL = time.time()


def _safe_call(fn, *args, **kwargs):
    """pykrx 호출 보호 — 네트워크/파싱 실패 시 None 반환."""
    if not _KRX_AVAILABLE:
        return None
    try:
        _throttle()
        return fn(*args, **kwargs)
    except Exception:
        return None


def fetch_foreign_ownership(ticker: str) -> Optional[dict]:
    """외국인 보유율 — 최근값 + 5일/20일 변화량.

    반환:
      {
        "available": True,
        "latest_pct": 50.43,             # 최근 외국인 보유율 (%)
        "latest_date": "2026-04-28",
        "limit_exhaustion_pct": 99.93,   # 한도 소진률 (%)
        "delta_5d_pct": 0.21,            # 5거래일 전 대비 변화 (%p)
        "delta_20d_pct": -0.45,          # 20거래일 전 대비 변화 (%p)
        "shares_held": 3010000000,       # 보유 주식수
        "shares_listed": 5969782550,     # 상장 주식수
      }
    """
    code = _stock_code(ticker)
    if not code:
        return None

    cache_key = f"krx_foreign:{code}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    end = _kst_today()
    start = _kst_days_ago(40)  # 영업일 20개 이상 확보용
    df = _safe_call(_krx_stock.get_exhaustion_rates_of_foreign_investment, start, end, code)
    if df is None or df.empty:
        cache.set(cache_key, None, _CACHE_TTL)
        return None

    try:
        df = df.sort_index()
        latest = df.iloc[-1]
        latest_date = df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], "strftime") else str(df.index[-1])
        latest_pct = float(latest.get("지분율", 0) or 0)
        limit_pct = float(latest.get("한도소진률", 0) or 0)
        shares_held = int(latest.get("보유수량", 0) or 0)
        shares_listed = int(latest.get("상장주식수", 0) or 0)

        # 5일/20일 전 비교 (영업일 기준 — 인덱스 위치로 접근)
        def _delta(rows_back: int):
            if len(df) < rows_back + 1:
                return None
            past = df.iloc[-1 - rows_back]
            past_pct = float(past.get("지분율", 0) or 0)
            return round(latest_pct - past_pct, 3)

        result = {
            "available": True,
            "latest_pct": round(latest_pct, 2),
            "latest_date": latest_date,
            "limit_exhaustion_pct": round(limit_pct, 2),
            "delta_5d_pct": _delta(5),
            "delta_20d_pct": _delta(20),
            "shares_held": shares_held,
            "shares_listed": shares_listed,
        }
        cache.set(cache_key, result, _CACHE_TTL)
        return result
    except Exception:
        cache.set(cache_key, None, _CACHE_TTL)
        return None


# 투자자 그룹 라벨 매핑 (pykrx 컬럼명 변동 대비 다중 시도)
_INVESTOR_GROUPS = {
    "foreign": ["외국인합계", "외국인"],
    "institution": ["기관합계", "기관"],
    "individual": ["개인"],
    "pension": ["연기금등", "연기금 등", "연기금"],
}


def _pick_col(row, candidates):
    """row(Series)에서 후보 컬럼명 중 존재하는 첫 값을 반환 (없으면 0)."""
    for c in candidates:
        if c in row.index:
            v = row.get(c)
            try:
                return float(v or 0)
            except (TypeError, ValueError):
                continue
    return 0.0


def fetch_investor_trading(ticker: str) -> Optional[dict]:
    """투자자별 일별 순매수 동향 — 최근 5일·20일 누적.

    반환:
      {
        "available": True,
        "currency": "KRW",
        "since_date": "2026-04-01",
        "until_date": "2026-04-28",
        "by_5d": {
            "foreign": -150000000000,        # 5일 누적 외국인 순매수 (원)
            "institution": 80000000000,
            "individual": 70000000000,
            "pension": 12000000000,
        },
        "by_20d": { ... },
      }
    """
    code = _stock_code(ticker)
    if not code:
        return None

    cache_key = f"krx_trading:{code}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    end = _kst_today()
    start = _kst_days_ago(40)
    df = _safe_call(_krx_stock.get_market_trading_value_by_investor, start, end, code)
    if df is None or df.empty:
        cache.set(cache_key, None, _CACHE_TTL)
        return None

    try:
        df = df.sort_index()

        def _agg(rows_back: int):
            tail = df.tail(rows_back)
            if tail.empty:
                return None
            agg = {}
            for grp, candidates in _INVESTOR_GROUPS.items():
                total = 0.0
                for c in candidates:
                    if c in tail.columns:
                        total = float(tail[c].sum())
                        break
                agg[grp] = round(total, 0)
            return agg

        result = {
            "available": True,
            "currency": "KRW",
            "since_date": df.index[0].strftime("%Y-%m-%d") if hasattr(df.index[0], "strftime") else str(df.index[0]),
            "until_date": df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], "strftime") else str(df.index[-1]),
            "by_5d": _agg(5),
            "by_20d": _agg(20),
        }
        cache.set(cache_key, result, _CACHE_TTL)
        return result
    except Exception:
        cache.set(cache_key, None, _CACHE_TTL)
        return None


def fetch_short_balance(ticker: str) -> Optional[dict]:
    """공매도 잔고 — 최근값 + 5일 변화.

    반환:
      {
        "available": True,
        "latest_balance": 12000000,        # 공매도 잔고 주식수
        "latest_balance_value": 850000000000,  # 공매도 잔고 평가액
        "latest_pct_of_listed": 0.20,      # 상장주식 대비 잔고비율 (%)
        "latest_date": "2026-04-25",
        "delta_5d_balance": 2000000,       # 5거래일 전 대비 잔고 변화
      }
    """
    code = _stock_code(ticker)
    if not code:
        return None

    cache_key = f"krx_short:{code}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    end = _kst_today()
    start = _kst_days_ago(15)
    df = _safe_call(_krx_stock.get_shorting_balance_by_date, start, end, code)
    if df is None or df.empty:
        cache.set(cache_key, None, _CACHE_TTL)
        return None

    try:
        df = df.sort_index()
        latest = df.iloc[-1]
        # 컬럼명: 공매도잔고, 공매도금액, 비중 (pykrx 버전마다 약간 다를 수 있음)
        balance = float(_pick_col(latest, ["공매도잔고", "잔고수량"]) or 0)
        balance_value = float(_pick_col(latest, ["공매도금액", "잔고금액"]) or 0)
        pct = float(_pick_col(latest, ["비중"]) or 0)

        delta_5d = None
        if len(df) >= 6:
            past = df.iloc[-6]
            past_balance = float(_pick_col(past, ["공매도잔고", "잔고수량"]) or 0)
            delta_5d = balance - past_balance

        result = {
            "available": True,
            "latest_balance": int(balance),
            "latest_balance_value": int(balance_value),
            "latest_pct_of_listed": round(pct, 3),
            "latest_date": df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], "strftime") else str(df.index[-1]),
            "delta_5d_balance": int(delta_5d) if delta_5d is not None else None,
        }
        cache.set(cache_key, result, _CACHE_TTL)
        return result
    except Exception:
        cache.set(cache_key, None, _CACHE_TTL)
        return None


def fetch_all(ticker: str) -> dict:
    """한국 종목 한 번에 — 외국인·매매·공매도 묶어서.

    하나라도 가져오면 available=True. 전부 실패하면 available=False.
    """
    if not _KRX_AVAILABLE:
        return {"available": False, "reason": "pykrx 미설치"}

    foreign = fetch_foreign_ownership(ticker)
    trading = fetch_investor_trading(ticker)
    short = fetch_short_balance(ticker)

    any_ok = any(x and x.get("available") for x in (foreign, trading, short))
    return {
        "available": any_ok,
        "foreign": foreign,
        "trading": trading,
        "short": short,
    }
