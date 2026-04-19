"""다년도 펀더멘털 추이 (yfinance 재무제표)."""

import math


def _pick(row, *keys):
    for k in keys:
        try:
            v = row.get(k)
        except Exception:
            v = None
        if v is None:
            continue
        try:
            f = float(v)
        except Exception:
            continue
        if math.isnan(f) or math.isinf(f):
            continue
        return f
    return None


def _cagr(first, last, years):
    if first is None or last is None or years <= 0 or first <= 0:
        return None
    if last <= 0:
        return None
    try:
        return (last / first) ** (1 / years) - 1
    except Exception:
        return None


def get_historical_metrics(stock) -> dict:
    try:
        inc = stock.income_stmt
        bs = stock.balance_sheet
        cf = stock.cashflow
    except Exception:
        return {"available": False}

    if inc is None or inc.empty:
        return {"available": False}

    cols = list(inc.columns)
    n = min(len(cols), 5)
    cols = cols[:n]
    years = [str(c.year) if hasattr(c, "year") else str(c) for c in cols][::-1]

    revenue, net_income, eps, roe, fcf = [], [], [], [], []

    for c in cols:
        # Revenue
        try:
            r = inc[c]
            rev = _pick(r, "Total Revenue", "Revenue", "Operating Revenue")
        except Exception:
            rev = None
        revenue.append(rev)

        # Net Income
        try:
            ni = _pick(r, "Net Income", "Net Income Common Stockholders", "Net Income From Continuing Operations")
        except Exception:
            ni = None
        net_income.append(ni)

        # Diluted EPS
        try:
            e = _pick(r, "Diluted EPS", "Basic EPS")
        except Exception:
            e = None
        eps.append(e)

        # ROE = NI / Equity
        equity = None
        if bs is not None and not bs.empty and c in bs.columns:
            try:
                br = bs[c]
                equity = _pick(br, "Stockholders Equity", "Total Stockholders Equity",
                               "Common Stock Equity", "Total Equity Gross Minority Interest")
            except Exception:
                equity = None
        if ni is not None and equity is not None and equity > 0:
            roe.append(ni / equity)
        else:
            roe.append(None)

        # FCF = OpCF - CapEx
        fcf_val = None
        if cf is not None and not cf.empty and c in cf.columns:
            try:
                cr = cf[c]
                ocf = _pick(cr, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
                            "Total Cash From Operating Activities")
                capex = _pick(cr, "Capital Expenditure", "Capital Expenditures")
                if ocf is not None:
                    fcf_val = ocf + (capex or 0)
                if fcf_val is None:
                    fcf_val = _pick(cr, "Free Cash Flow")
            except Exception:
                pass
        fcf.append(fcf_val)

    # Reverse to oldest→newest
    revenue = revenue[::-1]
    net_income = net_income[::-1]
    eps = eps[::-1]
    roe = roe[::-1]
    fcf = fcf[::-1]

    # ROE 일관성
    valid_roe = [r for r in roe if r is not None]
    years_above_15 = sum(1 for r in valid_roe if r >= 0.15)
    all_positive = all(r is not None and r > 0 for r in roe) if roe else False
    passed_buffett = years_above_15 >= max(3, len(valid_roe) - 0)  # need all measured years >= 15%

    # CAGR
    def valid_endpoints(lst):
        first_idx = next((i for i, v in enumerate(lst) if v is not None), None)
        last_idx = next((i for i in range(len(lst) - 1, -1, -1) if lst[i] is not None), None)
        if first_idx is None or last_idx is None or first_idx == last_idx:
            return None, None, 0
        return lst[first_idx], lst[last_idx], last_idx - first_idx

    rev_f, rev_l, rev_y = valid_endpoints(revenue)
    eps_f, eps_l, eps_y = valid_endpoints(eps)

    revenue_cagr = _cagr(rev_f, rev_l, rev_y)
    eps_cagr = _cagr(eps_f, eps_l, eps_y)

    return {
        "years": years,
        "revenue": revenue,
        "net_income": net_income,
        "eps": eps,
        "roe": roe,
        "fcf": fcf,
        "roe_consistency": {
            "years_above_15pct": years_above_15,
            "total_measured": len(valid_roe),
            "all_positive": all_positive,
            "passed_buffett_10yr_proxy": passed_buffett and len(valid_roe) >= 3,
        },
        "revenue_cagr": revenue_cagr,
        "eps_cagr": eps_cagr,
        "available": True,
    }
