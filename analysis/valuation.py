"""DCF / PER / Graham 기반 적정주가 추정."""

import math
from analysis.sector_baseline import get_sector_thresholds


def _dcf_fair_value(fcf: float, shares: float, growth_5y=0.10, terminal_growth=0.03, discount=0.09):
    if not fcf or fcf <= 0 or not shares or shares <= 0:
        return None
    pv = 0.0
    current_fcf = fcf
    for yr in range(1, 6):
        current_fcf *= (1 + growth_5y)
        pv += current_fcf / ((1 + discount) ** yr)
    terminal_fcf = current_fcf * (1 + terminal_growth)
    terminal_value = terminal_fcf / (discount - terminal_growth)
    pv += terminal_value / ((1 + discount) ** 5)
    return pv / shares


def _graham_number(eps: float, bvps: float):
    if not eps or not bvps or eps <= 0 or bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * bvps)


def calculate_fair_value(info: dict, stock) -> dict:
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not current_price:
        return {"available": False}

    sector = info.get("sector")
    st = get_sector_thresholds(sector)

    fcf = info.get("freeCashflow")
    shares = info.get("sharesOutstanding")
    eps = info.get("trailingEps")
    bvps = info.get("bookValue")

    methods = {}

    # DCF
    dcf_fv = _dcf_fair_value(fcf, shares)
    if dcf_fv is not None:
        methods["dcf"] = {
            "fair_value": round(dcf_fv, 2),
            "upside_pct": round((dcf_fv - current_price) / current_price * 100, 1),
            "assumptions": {"growth_5y": 0.10, "terminal_growth": 0.03, "discount_rate": 0.09},
        }

    # PER-based
    per_fv = None
    if eps and eps > 0:
        per_fv = eps * st["median_pe"]
        methods["per_based"] = {
            "fair_value": round(per_fv, 2),
            "upside_pct": round((per_fv - current_price) / current_price * 100, 1),
            "assumption_pe": st["median_pe"],
            "sector": st.get("sector", "Unknown"),
        }

    # Graham
    graham_fv = _graham_number(eps, bvps)
    if graham_fv is not None:
        methods["graham_number"] = round(graham_fv, 2)

    # Composite
    values = []
    if dcf_fv is not None:
        values.append(dcf_fv)
    if per_fv is not None:
        values.append(per_fv)
    if graham_fv is not None:
        values.append(graham_fv)

    if not values:
        return {"available": False, "current_price": round(current_price, 2)}

    composite = sum(values) / len(values)
    upside = (composite - current_price) / current_price * 100

    if upside >= 20:
        verdict = "크게 저평가 (적정가 대비 20%+ 할인)"
    elif upside >= 10:
        verdict = "저평가 (적정가 대비 10~20% 할인)"
    elif upside >= -10:
        verdict = "현재가가 적정가 근처 (±10%)"
    elif upside >= -20:
        verdict = "고평가 (적정가 대비 10~20% 프리미엄)"
    else:
        verdict = "크게 고평가 (적정가 대비 20%+ 프리미엄)"

    return {
        "current_price": round(current_price, 2),
        "dcf": methods.get("dcf"),
        "per_based": methods.get("per_based"),
        "graham_number": methods.get("graham_number"),
        "composite_fair_value": round(composite, 2),
        "upside_pct": round(upside, 1),
        "verdict": verdict,
        "available": True,
    }
