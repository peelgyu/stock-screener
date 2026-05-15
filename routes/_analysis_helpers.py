"""api_stock.py에서 사용하는 분석 헬퍼 — 라우트 파일 슬림화 목적 분리.

각 함수는 순수 dict 변환·메타데이터 생성용. 라우트와 분리하면 단위 테스트도 쉬워짐.

함수:
- _safe_call             함수 호출 + 예외 로깅 + default 반환 (thread-safe 로깅)
- _await_future          ThreadPoolExecutor future timeout 보호 (TimeoutError → default)
- _merge_dart_into_history  DART/SEC 공시 재무 → history 병합
- _populate_info_from_dart  DART/SEC 공시 → info(yfinance 형식) 보강
- _build_data_meta       응답 메타데이터 (시점·출처)
"""
import concurrent.futures
import logging
from datetime import datetime, timedelta, timezone

from flask import current_app

from data.cache import cache


_THREAD_LOGGER = logging.getLogger("stockinto.threadpool")


def _log_warning(msg: str) -> None:
    """app context 있으면 Flask logger, 없으면 표준 logging.

    ThreadPoolExecutor worker thread에서 호출돼도 RuntimeError 안 남.
    (Sentry PYTHON-2: 'Working outside of application context' 회귀 방지)
    """
    try:
        current_app.logger.warning(msg)
    except RuntimeError:
        _THREAD_LOGGER.warning(msg)


def _safe_call(fn, default, *args, **kwargs):
    """함수 호출 + 예외 시 default 반환 + thread-safe 로깅."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        _log_warning(f"{fn.__name__} failed: {e}")
        return default


def _await_future(future, timeout, default, label):
    """ThreadPoolExecutor future를 timeout 보호로 받음.

    timeout 시 default 반환 + 로깅. None future는 None 반환.
    (Sentry PYTHON-3: 'TimeoutError in api_stock.analyze' 회귀 방지)
    """
    if future is None:
        return None
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        _log_warning(f"{label} timeout after {timeout}s")
        return default
    except Exception as e:
        _log_warning(f"{label} raised {type(e).__name__}: {e}")
        return default


def _merge_dart_into_history(hist: dict, dart: dict, info: dict) -> dict:
    """DART/SEC 공시 재무를 history_data에 병합. 공시가 있는 연도는 공시 값 우선.

    info 파라미터: sharesOutstanding 조회용 (기존 closure 캡처 → 명시 인자로 변환).
    """
    if not isinstance(hist, dict):
        hist = {}
    years = dart.get("years") or []
    rev = dart.get("revenue") or []
    ni = dart.get("net_income") or []
    eq = dart.get("equity") or []
    oi = dart.get("operating_income") or [None] * len(years)
    gp = dart.get("gross_profit") or [None] * len(years)
    rd = dart.get("rd_expense") or [None] * len(years)
    fcf_dart = dart.get("fcf") or [None] * len(years)

    roe = []
    for n, e in zip(ni, eq):
        roe.append(n / e if (n is not None and e and e > 0) else None)

    gross_margins = []
    for g, r in zip(gp, rev):
        gross_margins.append(g / r if (g is not None and r and r > 0) else None)

    rd_ratios = []
    for x, r in zip(rd, rev):
        rd_ratios.append(x / r if (x is not None and r and r > 0) else None)

    orig_years = hist.get("years")
    can_reuse = isinstance(orig_years, list) and orig_years == years

    def _arr(key):
        v = hist.get(key) if can_reuse else None
        return v if isinstance(v, list) else [None] * len(years)

    hist = dict(hist)
    hist["available"] = True
    hist["years"] = years
    hist["revenue"] = rev
    hist["net_income"] = ni

    # EPS: yfinance가 있으면 사용, 없으면 NI/shares 로 근사
    shares = info.get("sharesOutstanding")
    if isinstance(hist.get("eps"), list) and any(v is not None for v in hist["eps"]) and can_reuse:
        hist["eps"] = hist["eps"]
    elif shares and shares > 0:
        hist["eps"] = [n / shares if n is not None else None for n in ni]
    else:
        hist["eps"] = _arr("eps")

    hist["roe"] = roe
    hist["fcf"] = fcf_dart
    hist["gross_margins"] = gross_margins
    hist["rd_ratios"] = rd_ratios

    # CAGR 재계산
    def _endpoints(lst):
        f = next((i for i, v in enumerate(lst) if v is not None), None)
        l = next((i for i in range(len(lst) - 1, -1, -1) if lst[i] is not None), None)
        if f is None or l is None or f == l:
            return None, None, 0
        return lst[f], lst[l], l - f

    def _cagr(first, last, y):
        if first is None or last is None or y <= 0 or first <= 0 or last <= 0:
            return None
        try:
            return (last / first) ** (1 / y) - 1
        except Exception:
            return None

    rf, rl, ry = _endpoints(rev)
    hist["revenue_cagr"] = _cagr(rf, rl, ry)

    # EPS CAGR도 계산
    eps_for_cagr = hist.get("eps") or []
    ef, el, ey = _endpoints(eps_for_cagr)
    hist["eps_cagr"] = _cagr(ef, el, ey)

    # ROE 일관성 재계산
    valid_roe = [r for r in roe if r is not None]
    years_above_15 = sum(1 for r in valid_roe if r >= 0.15)
    all_positive = all(r is not None and r > 0 for r in roe) if roe else False
    hist["roe_consistency"] = {
        "years_above_15pct": years_above_15,
        "total_measured": len(valid_roe),
        "all_positive": all_positive,
        "passed_buffett_10yr_proxy": years_above_15 >= max(3, len(valid_roe)) and len(valid_roe) >= 3,
    }

    # Gross Margin 안정성
    valid_gm = [g for g in gross_margins if g is not None]
    gm_avg = sum(valid_gm) / len(valid_gm) if valid_gm else None
    gm_std = None
    if len(valid_gm) >= 3 and gm_avg is not None:
        var = sum((g - gm_avg) ** 2 for g in valid_gm) / len(valid_gm)
        gm_std = var ** 0.5
    hist["gross_margin_analysis"] = {
        "avg": gm_avg,
        "std": gm_std,
        "stable": gm_std is not None and gm_std <= 0.05,
        "measured": len(valid_gm),
    }

    # R&D 투자
    valid_rd = [r for r in rd_ratios if r is not None]
    hist["rd_analysis"] = {
        "latest": rd_ratios[-1] if rd_ratios else None,
        "average": sum(valid_rd) / len(valid_rd) if valid_rd else None,
    }
    # source 라벨은 입력 데이터에서 받음 (DART/SEC EDGAR 등)
    hist["source"] = dart.get("source", "filings")
    return hist


def _populate_info_from_dart(info: dict, dart: dict) -> None:
    """DART/SEC 최신 연도 값으로 info(yfinance 형식) 보강 — 한국·미국 모든 종목 지표 활성화."""
    years = dart.get("years") or []
    if not years:
        return

    def _last(lst):
        for v in reversed(lst or []):
            if v is not None:
                return v
        return None

    rev = dart.get("revenue") or []
    ni = dart.get("net_income") or []
    oi = dart.get("operating_income") or []
    gp = dart.get("gross_profit") or []
    eq = dart.get("equity") or []
    debt = dart.get("total_liabilities") or []
    ca = dart.get("current_assets") or []
    cl = dart.get("current_liabilities") or []
    fcf = dart.get("fcf") or []

    rev_l = _last(rev); ni_l = _last(ni); oi_l = _last(oi); gp_l = _last(gp)
    eq_l = _last(eq); debt_l = _last(debt); ca_l = _last(ca); cl_l = _last(cl); fcf_l = _last(fcf)

    # yfinance 값이 이미 있으면 덮지 않음 (있는 게 더 정확할 수도)
    def _set_if_missing(key, val):
        if val is not None and info.get(key) in (None, 0):
            info[key] = val

    _set_if_missing("totalRevenue", rev_l)
    _set_if_missing("freeCashflow", fcf_l)
    _set_if_missing("totalDebt", debt_l)

    if ni_l is not None and eq_l and eq_l > 0:
        _set_if_missing("returnOnEquity", ni_l / eq_l)
    if debt_l is not None and eq_l and eq_l > 0:
        # Yahoo의 debtToEquity는 %(예: 120) 단위
        _set_if_missing("debtToEquity", (debt_l / eq_l) * 100)
    if oi_l is not None and rev_l and rev_l > 0:
        _set_if_missing("operatingMargins", oi_l / rev_l)
    if gp_l is not None and rev_l and rev_l > 0:
        _set_if_missing("grossMargins", gp_l / rev_l)
    if ni_l is not None and rev_l and rev_l > 0:
        _set_if_missing("profitMargins", ni_l / rev_l)
    if ca_l is not None and cl_l and cl_l > 0:
        cr = ca_l / cl_l
        # 정상 유동비율 범위 (30%~500%) — 벗어나면 BS 매칭 실패 가능성, 저장 안 함
        # 한국 DART는 회사별 BS 항목명이 다양해서 잘못된 매칭으로 비현실적 값 나올 수 있음
        if 0.3 <= cr <= 5.0:
            _set_if_missing("currentRatio", cr)

    # YoY 성장률
    rev_vals = [v for v in rev if v is not None]
    if len(rev_vals) >= 2 and rev_vals[-2] > 0:
        _set_if_missing("revenueGrowth", (rev_vals[-1] - rev_vals[-2]) / rev_vals[-2])
    ni_vals = [v for v in ni if v is not None]
    if len(ni_vals) >= 2 and ni_vals[-2] != 0:
        _set_if_missing("earningsGrowth", (ni_vals[-1] - ni_vals[-2]) / abs(ni_vals[-2]))

    # EPS / PER / PBR / PEG — sharesOutstanding 우선, 없으면 marketCap/price 역산
    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or info.get("floatShares")
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    # yfinance가 한국 종목에 sharesOutstanding 안 주는 경우 — 시가총액에서 역산
    if (not shares or shares <= 0) and price and price > 0:
        mcap = info.get("marketCap")
        if mcap and mcap > 0:
            shares = mcap / price
            # info에도 박아둠 (다른 곳에서 재사용)
            info["sharesOutstanding"] = shares
    if shares and shares > 0:
        if ni_l is not None:
            eps = ni_l / shares
            _set_if_missing("trailingEps", eps)
            if price and price > 0 and eps > 0:
                _set_if_missing("trailingPE", price / eps)
        if eq_l is not None and eq_l > 0:
            bps = eq_l / shares
            _set_if_missing("bookValue", bps)
            if price and price > 0 and bps > 0:
                _set_if_missing("priceToBook", price / bps)
        # PEG
        pe = info.get("trailingPE")
        eg = info.get("earningsGrowth")
        if pe and eg and eg > 0:
            _set_if_missing("pegRatio", pe / (eg * 100))


def _build_data_meta(info: dict, ticker: str, is_kr: bool, history_data: dict | None) -> dict:
    """응답 메타데이터 — 사용자가 데이터 시점·출처를 즉시 이해할 수 있게.

    법적 보호: 자본시장법상 정보 제공자임을 명시 + 시점 명확화 (조언 아님).
    """
    kst = datetime.now(timezone(timedelta(hours=9)))
    sec_ttm = info.get("_sec_ttm")
    dart_used = info.get("_data_source_dart")

    # 재무 데이터 출처
    if is_kr and dart_used:
        fin_source = "금융감독원 DART (공공누리 1유형)"
        fin_source_short = "DART"
    elif sec_ttm:
        fin_source = "SEC EDGAR (Public Domain · 17 USC §105)"
        fin_source_short = "SEC EDGAR"
    else:
        fin_source = "Yahoo Finance (재무 추정치)"
        fin_source_short = "Yahoo Finance"

    # 재무 데이터 기준일
    fin_end_date = None
    fin_period_type = None
    if sec_ttm:
        # SEC TTM 정보는 info에 직접 안 박혔으니 재호출은 비용 → 캐시에서 가져옴
        cik = None
        try:
            from data.sec_client import _get_cik
            cik = _get_cik(ticker)
        except Exception:
            pass
        if cik:
            cached_ttm = cache.get(f"sec_ttm_v1:{cik}")
            if cached_ttm and isinstance(cached_ttm, dict):
                fin_end_date = cached_ttm.get("ttm_end_date") or cached_ttm.get("balance_end_date")
                fin_period_type = "TTM (12개월 누적)"
    if not fin_end_date and history_data and history_data.get("years"):
        years = history_data["years"]
        if years:
            fin_end_date = f"{years[-1]}-12-31"
            fin_period_type = "연간 (FY 결산)"

    return {
        "analysisTimeKST": kst.strftime("%Y-%m-%d %H:%M KST"),
        "analysisTimeISO": kst.isoformat(),
        "financialSource": fin_source,
        "financialSourceShort": fin_source_short,
        "financialEndDate": fin_end_date,         # "2025-09-27" 같은 날짜
        "financialPeriodType": fin_period_type,    # "TTM (12개월 누적)" 또는 "연간 (FY 결산)"
        "priceDelayMinutes": 15,
        "priceProviderShort": "Yahoo Finance" if not is_kr else "FinanceDataReader (KRX)",
        "fxRateDate": kst.strftime("%Y-%m-%d"),    # 환율 fetch 시점 (당일 단위)
        "marketCurrency": "KRW" if is_kr else "USD",
        "disclaimer": "본 분석은 위 시점의 공시 데이터 기준이며, 그 이후 시장 변동은 미반영. 투자 자문이 아닌 정보 제공입니다.",
    }
