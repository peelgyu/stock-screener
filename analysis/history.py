"""다년도 펀더멘털 추이 (yfinance 재무제표)."""

import logging
import math

logger = logging.getLogger(__name__)


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
    except Exception as e:
        logger.warning("Financial statements unavailable: %s", e)
        return {"available": False}

    if inc is None or inc.empty:
        return {"available": False}

    cols = list(inc.columns)
    n = min(len(cols), 5)
    cols = cols[:n]
    years = [str(c.year) if hasattr(c, "year") else str(c) for c in cols][::-1]

    revenue, net_income, eps, roe, fcf = [], [], [], [], []
    gross_margins, rd_ratios = [], []

    for c in cols:
        # Revenue
        try:
            r = inc[c]
            rev = _pick(r, "Total Revenue", "Revenue", "Operating Revenue")
        except Exception:
            rev = None
        revenue.append(rev)

        # Gross Margin = Gross Profit / Revenue
        try:
            gp = _pick(r, "Gross Profit")
            if gp is None:
                # 매출 - 매출원가 계산 fallback
                cost = _pick(r, "Cost Of Revenue", "Cost Of Goods Sold", "Reconciled Cost Of Revenue")
                if rev is not None and cost is not None:
                    gp = rev - cost
            if gp is not None and rev and rev > 0:
                gross_margins.append(gp / rev)
            else:
                gross_margins.append(None)
        except Exception:
            gross_margins.append(None)

        # R&D Ratio = R&D Expense / Revenue
        try:
            rnd = _pick(r, "Research And Development", "Research Development",
                        "Research And Development Expenses")
            if rnd is not None and rev and rev > 0:
                rd_ratios.append(rnd / rev)
            else:
                rd_ratios.append(None)
        except Exception:
            rd_ratios.append(None)

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
    gross_margins = gross_margins[::-1]
    rd_ratios = rd_ratios[::-1]

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

    # Gross Margin 안정성 — 표준편차
    valid_gm = [g for g in gross_margins if g is not None]
    gm_avg = sum(valid_gm) / len(valid_gm) if valid_gm else None
    gm_std = None
    if len(valid_gm) >= 3 and gm_avg is not None:
        variance = sum((g - gm_avg) ** 2 for g in valid_gm) / len(valid_gm)
        gm_std = math.sqrt(variance)
    gm_stable = gm_std is not None and gm_std <= 0.05  # 5%p 이하 편차면 안정

    # R&D 투자 — 최근 연도
    rd_latest = rd_ratios[-1] if rd_ratios and rd_ratios[-1] is not None else None
    rd_avg = sum([r for r in rd_ratios if r is not None]) / max(1, len([r for r in rd_ratios if r is not None])) if rd_ratios else None

    return {
        "years": years,
        "revenue": revenue,
        "net_income": net_income,
        "eps": eps,
        "roe": roe,
        "fcf": fcf,
        "gross_margins": gross_margins,
        "rd_ratios": rd_ratios,
        "roe_consistency": {
            "years_above_15pct": years_above_15,
            "total_measured": len(valid_roe),
            "all_positive": all_positive,
            "passed_buffett_10yr_proxy": passed_buffett and len(valid_roe) >= 3,
        },
        "gross_margin_analysis": {
            "avg": gm_avg,
            "std": gm_std,
            "stable": gm_stable,
            "measured": len(valid_gm),
        },
        "rd_analysis": {
            "latest": rd_latest,
            "average": rd_avg,
        },
        "revenue_cagr": revenue_cagr,
        "eps_cagr": eps_cagr,
        "available": True,
    }
