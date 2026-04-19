"""재무 품질 (어닝 퀄리티) 분석."""

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


def evaluate_earnings_quality(stock, info: dict) -> dict:
    try:
        inc = stock.income_stmt
        bs = stock.balance_sheet
        cf = stock.cashflow
    except Exception:
        return {"available": False}

    if inc is None or inc.empty or bs is None or bs.empty:
        return {"available": False}

    flags = []
    strengths = []
    scores = []

    latest_inc = inc.iloc[:, 0]
    latest_bs = bs.iloc[:, 0]
    latest_cf = cf.iloc[:, 0] if (cf is not None and not cf.empty) else None

    net_income = _pick(latest_inc, "Net Income", "Net Income Common Stockholders")
    revenue = _pick(latest_inc, "Total Revenue", "Revenue")
    total_assets = _pick(latest_bs, "Total Assets")
    ar = _pick(latest_bs, "Accounts Receivable", "Receivables", "Net Receivables")
    inventory = _pick(latest_bs, "Inventory")

    ocf = None
    if latest_cf is not None:
        ocf = _pick(latest_cf, "Operating Cash Flow",
                    "Cash Flow From Continuing Operating Activities",
                    "Total Cash From Operating Activities")
    fcf = info.get("freeCashflow")

    # 1) FCF / NI 비율
    fcf_ni_ratio = None
    if fcf is not None and net_income and net_income > 0:
        fcf_ni_ratio = fcf / net_income
        if fcf_ni_ratio >= 1.0:
            strengths.append("FCF > 순이익 (우량한 현금 창출)")
            scores.append(100)
        elif fcf_ni_ratio >= 0.7:
            strengths.append("FCF가 순이익 대비 양호 (70%+)")
            scores.append(75)
        elif fcf_ni_ratio >= 0.4:
            flags.append(f"FCF가 순이익 대비 낮음 ({fcf_ni_ratio*100:.0f}%) — 현금 전환력 약화")
            scores.append(45)
        else:
            flags.append(f"FCF/순이익 비율 매우 낮음 ({fcf_ni_ratio*100:.0f}%) — 장부이익과 현금괴리 큼")
            scores.append(20)

    # 2) Accruals ratio = (NI - OCF) / Total Assets
    accruals_ratio = None
    if net_income is not None and ocf is not None and total_assets and total_assets > 0:
        accruals_ratio = (net_income - ocf) / total_assets
        if accruals_ratio <= 0.05:
            strengths.append("발생액 비율 낮음 (회계 보수적)")
            scores.append(85)
        elif accruals_ratio <= 0.10:
            scores.append(60)
        else:
            flags.append(f"발생액 비율 높음 ({accruals_ratio*100:.1f}%) — 공격적 회계 가능성")
            scores.append(30)

    # 3) 매출채권 증가율 vs 매출 증가율
    ar_growth_vs_rev = None
    if inc.shape[1] >= 2 and bs.shape[1] >= 2:
        prev_inc = inc.iloc[:, 1]
        prev_bs = bs.iloc[:, 1]
        prev_rev = _pick(prev_inc, "Total Revenue", "Revenue")
        prev_ar = _pick(prev_bs, "Accounts Receivable", "Receivables", "Net Receivables")
        if revenue and prev_rev and prev_rev > 0 and ar and prev_ar and prev_ar > 0:
            rev_growth = (revenue - prev_rev) / prev_rev
            ar_growth = (ar - prev_ar) / prev_ar
            ar_growth_vs_rev = ar_growth - rev_growth
            if ar_growth_vs_rev > 0.15:
                flags.append(f"매출채권이 매출보다 {ar_growth_vs_rev*100:.0f}%p 더 빠르게 증가 — 매출 푸싱 의심")
                scores.append(30)
            elif ar_growth_vs_rev < -0.05:
                strengths.append("매출채권 회전 개선 (현금회수 빨라짐)")
                scores.append(80)
            else:
                scores.append(65)

    # 4) 재고 증가율 vs 매출 증가율
    inv_growth_vs_rev = None
    if inc.shape[1] >= 2 and bs.shape[1] >= 2:
        prev_inc2 = inc.iloc[:, 1]
        prev_bs2 = bs.iloc[:, 1]
        prev_rev2 = _pick(prev_inc2, "Total Revenue", "Revenue")
        prev_inv = _pick(prev_bs2, "Inventory")
        if revenue and prev_rev2 and prev_rev2 > 0 and inventory and prev_inv and prev_inv > 0:
            rev_g = (revenue - prev_rev2) / prev_rev2
            inv_g = (inventory - prev_inv) / prev_inv
            inv_growth_vs_rev = inv_g - rev_g
            if inv_growth_vs_rev > 0.20:
                flags.append(f"재고가 매출보다 {inv_growth_vs_rev*100:.0f}%p 더 빠르게 증가 — 판매둔화/악성재고 우려")
                scores.append(35)
            elif inv_growth_vs_rev < -0.05:
                strengths.append("재고 회전 개선")
                scores.append(80)

    # 5) 순이익이 음수면 큰 위험
    if net_income is not None and net_income < 0:
        flags.append("순이익 적자 — 품질 지표 의미 제한적")
        scores.append(15)

    quality_score = round(sum(scores) / len(scores)) if scores else None

    return {
        "fcf_ni_ratio": round(fcf_ni_ratio, 2) if fcf_ni_ratio is not None else None,
        "accruals_ratio": round(accruals_ratio, 3) if accruals_ratio is not None else None,
        "ar_growth_vs_rev": round(ar_growth_vs_rev, 3) if ar_growth_vs_rev is not None else None,
        "inventory_growth_vs_rev": round(inv_growth_vs_rev, 3) if inv_growth_vs_rev is not None else None,
        "quality_score": quality_score,
        "flags": flags,
        "strengths": strengths,
        "available": quality_score is not None,
    }
