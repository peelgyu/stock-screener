"""유명 투자자 기준 주식 스크리너 - Flask 웹앱 (개선판)."""

import os
import math
import time
import urllib.request
import urllib.parse
import json as json_lib
from collections import defaultdict

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from flask import Flask, render_template, request, jsonify, redirect, send_from_directory
from flask.json.provider import DefaultJSONProvider
import yfinance as yf
import numpy as np


class SafeJSONProvider(DefaultJSONProvider):
    """NaN/Infinity를 null로 변환해 JavaScript 호환 JSON 생성."""
    def dumps(self, obj, **kwargs):
        def clean(o):
            if isinstance(o, float):
                if math.isnan(o) or math.isinf(o):
                    return None
                return o
            if isinstance(o, dict):
                return {k: clean(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return [clean(v) for v in o]
            return o
        kwargs.setdefault("ensure_ascii", False)
        kwargs.setdefault("allow_nan", False)
        return json_lib.dumps(clean(obj), **kwargs)

from kr_stocks import search_kr_stocks, KR_STOCKS, US_STOCKS_KR
from data.cache import cache, cached
from data.fetcher import fetch_stock_data, detect_fetch_error_type
from data import dart_client
from analysis.sector_baseline import get_sector_thresholds
from analysis.history import get_historical_metrics
from analysis.quality import evaluate_earnings_quality
from analysis.valuation import calculate_fair_value
from analysis.rs_rating import calculate_rs_rating
from analysis.market_regime import get_market_regime
from analysis.oneil_v2 import evaluate_oneil
from analysis.fear_greed_v2 import evaluate_fear_greed
from analysis.options_v2 import evaluate_options
from analysis.verdict import generate_verdict
from analysis.most_active import get_most_active

app = Flask(__name__)
app.json = SafeJSONProvider(app)

RATE_LIMIT_PER_MIN = 30
_rate_bucket: dict = defaultdict(list)


CANONICAL_HOST = "stockinto.com"
REDIRECT_HOSTS = {"stockinto.co.kr", "www.stockinto.co.kr", "www.stockinto.com"}


@app.before_request
def _canonical_redirect():
    """`.co.kr` 및 `www.` 접속을 `stockinto.com`으로 301 리다이렉트 (SEO 최적화)."""
    host = (request.host or "").lower().split(":")[0]
    if host in REDIRECT_HOSTS:
        path = request.full_path if request.query_string else request.path
        path = path.rstrip("?")
        return redirect(f"https://{CANONICAL_HOST}{path}", code=301)
    return None


@app.errorhandler(500)
def _handle_500(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": f"서버 내부 오류: {type(e).__name__}"}), 500
    return "Internal Server Error", 500


@app.errorhandler(Exception)
def _handle_exc(e):
    if request.path.startswith("/api/"):
        app.logger.exception("API exception")
        return jsonify({"error": f"처리 중 오류 발생: {type(e).__name__}: {str(e)[:200]}"}), 500
    raise e


@app.before_request
def _rate_limit():
    if not request.path.startswith("/api/"):
        return None
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0]).strip()
    now = time.time()
    bucket = [t for t in _rate_bucket[ip] if now - t < 60]
    if len(bucket) >= RATE_LIMIT_PER_MIN:
        _rate_bucket[ip] = bucket
        return jsonify({"error": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."}), 429
    bucket.append(now)
    _rate_bucket[ip] = bucket
    return None


def safe_get(info: dict, key: str, default=None):
    val = info.get(key, default)
    return val if val is not None else default


@cached(ttl=1800)  # 30분 캐시 — Yahoo 레이트리밋 완화
def get_stock_data(ticker: str) -> dict | None:
    # 통합 fetcher: yfinance 우선, 실패 시 FDR fallback (한국만)
    fetched = fetch_stock_data(ticker)
    if fetched is None:
        return None

    info = fetched["info"]
    stock = fetched["stock"]
    source = fetched["source"]

    # FDR fallback인 경우: 재무제표 보강 로직 스킵 (stock=None이라 호출 불가)
    if source == "fdr":
        # FDR이 제공하는 hist DataFrame을 1년치로 슬라이스
        fdr_hist = fetched.get("hist")
        try:
            if fdr_hist is not None and not fdr_hist.empty:
                hist = fdr_hist.tail(252)  # 최근 1년
            else:
                hist = None
        except Exception:
            hist = None
        return {"info": info, "hist": hist, "stock": None, "source": "fdr"}

    try:
        warnings: list = []

        try:
            bs = stock.balance_sheet
            inc = stock.income_stmt
            if bs is not None and not bs.empty and inc is not None and not inc.empty:
                latest_bs = bs.iloc[:, 0]
                latest_inc = inc.iloc[:, 0]

                if info.get("returnOnEquity") is None:
                    net_income = latest_inc.get("Net Income") or latest_inc.get("Net Income Common Stockholders")
                    equity = latest_bs.get("Stockholders Equity") or latest_bs.get("Total Stockholders Equity") or latest_bs.get("Common Stock Equity")
                    if net_income is not None and equity is not None and equity != 0:
                        info["returnOnEquity"] = float(net_income / equity)
                        info["_roe_note"] = "자본잠식" if equity < 0 else ""

                if info.get("debtToEquity") is None:
                    total_debt = latest_bs.get("Total Debt") or latest_bs.get("Total Liabilities Net Minority Interest")
                    equity = latest_bs.get("Stockholders Equity") or latest_bs.get("Total Stockholders Equity") or latest_bs.get("Common Stock Equity")
                    if total_debt is not None and equity is not None and equity != 0:
                        info["debtToEquity"] = float(total_debt / equity * 100)
                        info["_de_note"] = "자본잠식" if equity < 0 else ""

                if info.get("earningsGrowth") is None and inc.shape[1] >= 2:
                    ni_curr = inc.iloc[:, 0].get("Net Income") or inc.iloc[:, 0].get("Net Income Common Stockholders")
                    ni_prev = inc.iloc[:, 1].get("Net Income") or inc.iloc[:, 1].get("Net Income Common Stockholders")
                    if ni_curr is not None and ni_prev is not None and ni_prev != 0:
                        info["earningsGrowth"] = float((ni_curr - ni_prev) / abs(ni_prev))
        except Exception as e:
            warnings.append(f"재무제표 로드 실패: {type(e).__name__}")

        try:
            q_inc = stock.quarterly_income_stmt
            if info.get("earningsQuarterlyGrowth") is None and q_inc is not None and not q_inc.empty and q_inc.shape[1] >= 5:
                ni_curr = q_inc.iloc[:, 0].get("Net Income") or q_inc.iloc[:, 0].get("Net Income Common Stockholders")
                ni_yoy = q_inc.iloc[:, 4].get("Net Income") or q_inc.iloc[:, 4].get("Net Income Common Stockholders")
                if ni_curr is not None and ni_yoy is not None and ni_yoy != 0:
                    info["earningsQuarterlyGrowth"] = float((ni_curr - ni_yoy) / abs(ni_yoy))
        except Exception:
            pass

        hist = stock.history(period="1y")

        # 결측 지표 기록
        for k, label in [
            ("heldPercentInstitutions", "기관 보유율"),
            ("sharesShort", "공매도 수량"),
            ("shortPercentOfFloat", "공매도 비율"),
            ("trailingPE", "PER"),
            ("priceToBook", "PBR"),
            ("pegRatio", "PEG"),
        ]:
            if info.get(k) is None:
                warnings.append(f"{label} 데이터 없음")

        info["_data_warnings"] = warnings
        return {"info": info, "hist": hist, "stock": stock}
    except Exception:
        return None


def evaluate_positions(data: dict) -> dict:
    info = data["info"]
    short_data, long_data = [], []

    shares_short = safe_get(info, "sharesShort")
    if shares_short is not None:
        if shares_short >= 1e9:
            val = f"{shares_short/1e9:.2f}B"
        elif shares_short >= 1e6:
            val = f"{shares_short/1e6:.1f}M"
        else:
            val = f"{shares_short/1e3:.0f}K"
        short_data.append({"name": "공매도 수량", "value": val})

    short_pct = safe_get(info, "shortPercentOfFloat")
    if short_pct is not None:
        if short_pct >= 0.20:
            level = " (매우 높음 - 숏스퀴즈 주의)"
        elif short_pct >= 0.10:
            level = " (높음)"
        elif short_pct >= 0.05:
            level = " (보통)"
        else:
            level = " (낮음)"
        short_data.append({"name": "공매도 비율 (유통주식 대비)", "value": f"{short_pct*100:.1f}%{level}"})

    short_ratio = safe_get(info, "shortRatio")
    if short_ratio is not None:
        if short_ratio >= 10:
            level = " (숏커버 어려움)"
        elif short_ratio >= 5:
            level = " (높음)"
        else:
            level = " (보통)"
        short_data.append({"name": "숏 커버 일수 (Days to Cover)", "value": f"{short_ratio:.1f}일{level}"})

    shares_short_prev = safe_get(info, "sharesShortPriorMonth")
    if shares_short is not None and shares_short_prev is not None and shares_short_prev > 0:
        change = (shares_short - shares_short_prev) / shares_short_prev * 100
        direction = "증가" if change > 0 else "감소"
        short_data.append({"name": "전월 대비 공매도 변화", "value": f"{change:+.1f}% ({direction})"})

    inst_pct = safe_get(info, "heldPercentInstitutions")
    if inst_pct is not None:
        long_data.append({"name": "기관 보유 비율", "value": f"{inst_pct*100:.1f}%"})

    insider_pct = safe_get(info, "heldPercentInsiders")
    if insider_pct is not None:
        long_data.append({"name": "내부자 보유 비율", "value": f"{insider_pct*100:.1f}%"})

    for key, name in [("floatShares", "유통 주식수"), ("sharesOutstanding", "총 발행 주식수")]:
        v = safe_get(info, key)
        if v is not None:
            if v >= 1e9:
                val = f"{v/1e9:.2f}B"
            elif v >= 1e6:
                val = f"{v/1e6:.0f}M"
            else:
                val = f"{v/1e3:.0f}K"
            long_data.append({"name": name, "value": val})

    sentiment = "중립"
    sentiment_detail = ""
    if short_pct is not None:
        if short_pct >= 0.20:
            sentiment, sentiment_detail = "강한 약세 베팅", "공매도 비율이 매우 높아 숏스퀴즈 가능성 있음"
        elif short_pct >= 0.10:
            sentiment, sentiment_detail = "약세 베팅 우세", "공매도가 상당히 잡혀있어 하락 압력 존재"
        elif short_pct >= 0.05:
            sentiment, sentiment_detail = "소폭 약세", "적당한 수준의 공매도"
        else:
            sentiment, sentiment_detail = "강세 우세", "공매도가 적어 시장이 낙관적"

    return {"short": short_data, "long": long_data, "sentiment": sentiment, "sentimentDetail": sentiment_detail}


# ──────────────────────────────────────────────
# 투자자 기준 — 섹터 상대 기준 반영
# ──────────────────────────────────────────────
def evaluate_buffett(info: dict, sector_t: dict, history_data: dict | None = None, fair_value: dict | None = None) -> list[dict]:
    """버핏 9대 기준 — 원조 5개 + 개선 4개 (다년도 ROE·해자·안전마진)."""
    results = []

    # ===== 원조 5개 =====

    # 1. ROE (섹터 기준)
    roe = safe_get(info, "returnOnEquity")
    if roe is not None:
        note = info.get("_roe_note", "")
        val_str = f"{roe*100:.1f}%" + (f" ({note})" if note else "")
        results.append({"name": f"ROE >= {sector_t['roe_min']*100:.0f}% (섹터 기준)",
                        "passed": roe >= sector_t['roe_min'] and note != "자본잠식",
                        "value": val_str})
    else:
        results.append({"name": "ROE (섹터 기준)", "passed": None, "value": "데이터 없음"})

    # 2. 부채비율
    de = safe_get(info, "debtToEquity")
    if de is not None:
        note = info.get("_de_note", "")
        val_str = f"{de:.1f}%" + (f" ({note})" if note else "")
        results.append({"name": f"부채비율 <= {sector_t['de_max']}% (섹터 기준)",
                        "passed": de <= sector_t['de_max'] and de > 0 and note != "자본잠식",
                        "value": val_str})
    else:
        results.append({"name": "부채비율 (섹터 기준)", "passed": None, "value": "데이터 없음"})

    # 3. 영업이익률
    om = safe_get(info, "operatingMargins")
    if om is not None:
        results.append({"name": f"영업이익률 >= {sector_t['om_min']*100:.0f}% (섹터 기준)",
                        "passed": om >= sector_t['om_min'], "value": f"{om*100:.1f}%"})
    else:
        results.append({"name": "영업이익률 (섹터 기준)", "passed": None, "value": "데이터 없음"})

    # 4. 매출 성장
    rg = safe_get(info, "revenueGrowth")
    if rg is not None:
        results.append({"name": "매출 성장 중", "passed": rg > 0, "value": f"{rg*100:.1f}%"})
    else:
        results.append({"name": "매출 성장 중", "passed": None, "value": "데이터 없음"})

    # 5. FCF 양수
    fcf = safe_get(info, "freeCashflow")
    if fcf is not None:
        results.append({"name": "FCF 양수", "passed": fcf > 0, "value": f"${fcf/1e9:.2f}B"})
    else:
        results.append({"name": "FCF 양수", "passed": None, "value": "데이터 없음"})

    # ===== 개선 4개 (실제 버핏 철학 반영) =====

    # 6. ROE 꾸준함 (여러 해 연속 15%+)
    if history_data and history_data.get("available") and history_data.get("roe_consistency"):
        rc = history_data["roe_consistency"]
        years_above = rc.get("years_above_15pct", 0)
        total = rc.get("total_measured", 0)
        # 측정된 기간의 60%+ 연도에서 ROE 15%+ 달성
        passed = total >= 3 and years_above >= max(3, int(total * 0.6))
        results.append({
            "name": "ROE 꾸준함 (다년도 15%+)",
            "passed": passed if total >= 3 else None,
            "value": f"{years_above}/{total}년" if total > 0 else "데이터 없음"
        })
    else:
        results.append({"name": "ROE 꾸준함 (다년도 15%+)", "passed": None, "value": "데이터 없음"})

    # 7. Gross Margin 안정성 (편차 5%p 이하)
    if history_data and history_data.get("gross_margin_analysis"):
        gma = history_data["gross_margin_analysis"]
        std = gma.get("std")
        avg = gma.get("avg")
        measured = gma.get("measured", 0)
        if std is not None and avg is not None and measured >= 3:
            results.append({
                "name": "Gross Margin 안정 (편차 ≤5%p)",
                "passed": std <= 0.05,
                "value": f"평균 {avg*100:.1f}% · 편차 {std*100:.1f}%p"
            })
        else:
            results.append({"name": "Gross Margin 안정", "passed": None, "value": "데이터 부족"})
    else:
        results.append({"name": "Gross Margin 안정", "passed": None, "value": "데이터 없음"})

    # 8. R&D 투자 적극성 (섹터별 기준)
    if history_data and history_data.get("rd_analysis"):
        rda = history_data["rd_analysis"]
        rd = rda.get("latest")
        sector = info.get("sector", "")
        # 섹터별 R&D 기대값: Tech 5%+, Healthcare 8%+, 그 외 1%+ (있기만 하면 OK)
        rd_threshold = {
            "Technology": 0.05,
            "Healthcare": 0.08,
            "Communication Services": 0.05,
        }.get(sector, 0.01)
        if rd is not None:
            results.append({
                "name": f"R&D 투자 (매출 대비 {rd_threshold*100:.0f}%+)",
                "passed": rd >= rd_threshold,
                "value": f"{rd*100:.1f}%"
            })
        else:
            # R&D 없는 섹터는 자동 통과 (금융·유틸 등)
            if sector in ("Financial Services", "Utilities", "Real Estate", "Energy"):
                results.append({
                    "name": "R&D 투자 (섹터 특성)",
                    "passed": True,
                    "value": f"{sector} — 해당 없음"
                })
            else:
                results.append({"name": "R&D 투자", "passed": None, "value": "데이터 없음"})
    else:
        results.append({"name": "R&D 투자", "passed": None, "value": "데이터 없음"})

    # 9. 안전마진 30%+ (저평가)
    if fair_value and fair_value.get("available"):
        upside = fair_value.get("upside_pct", 0) or 0
        # upside_pct가 양수면 저평가 = 안전마진 존재
        results.append({
            "name": "안전마진 30%+ (저평가)",
            "passed": upside >= 30,
            "value": f"{upside:+.1f}% (기준 +30%)"
        })
    else:
        results.append({"name": "안전마진 30%+ (저평가)", "passed": None, "value": "데이터 없음"})

    return results


def buffett_strict_grade(yes: int, total: int) -> dict:
    """버핏 전용 엄격 등급제 (9개 기준 가정).

    9/9  = A+ (코카콜라·애플급 완벽)
    8/9  = A  (버핏 관심 최상위)
    7/9  = B  (좋은 회사)
    5-6/9= C  (부분 충족)
    3-4/9= D  (철학 미달)
    0-2/9= F  (버핏 안 산다)
    """
    if total == 0:
        return {"grade": "N/A", "text": "데이터 부족", "color": "gray"}
    if yes >= 9:
        return {"grade": "A+", "text": "버핏이 대량 매수할 종목", "color": "green"}
    if yes >= 8:
        return {"grade": "A", "text": "버핏 관심 최상위", "color": "green"}
    if yes >= 7:
        return {"grade": "B", "text": "좋은 회사, 가격만 맞으면", "color": "green"}
    if yes >= 5:
        return {"grade": "C", "text": "해자는 있지만 약점 존재", "color": "yellow"}
    if yes >= 3:
        return {"grade": "D", "text": "버핏 철학 미달", "color": "red"}
    return {"grade": "F", "text": "버핏이 안 사는 종목", "color": "red"}


def evaluate_graham(info: dict, sector_t: dict) -> list[dict]:
    results = []
    per = safe_get(info, "trailingPE")
    per_max = min(15, sector_t["per_max"])  # Graham은 보수적이라 섹터 최대치와 15 중 작은 값
    if per is not None:
        results.append({"name": f"PER <= {per_max}", "passed": 0 < per <= per_max, "value": f"{per:.1f}"})
    else:
        results.append({"name": f"PER <= {per_max}", "passed": None, "value": "데이터 없음"})

    pbr = safe_get(info, "priceToBook")
    pbr_max = min(1.5, sector_t["pbr_max"])
    if pbr is not None:
        results.append({"name": f"PBR <= {pbr_max}", "passed": 0 < pbr <= pbr_max, "value": f"{pbr:.2f}"})
    else:
        results.append({"name": f"PBR <= {pbr_max}", "passed": None, "value": "데이터 없음"})

    if per and pbr and per > 0 and pbr > 0:
        p = per * pbr
        results.append({"name": "PER x PBR < 22.5", "passed": p < 22.5, "value": f"{p:.1f}"})
    else:
        results.append({"name": "PER x PBR < 22.5", "passed": None, "value": "데이터 없음"})

    cr = safe_get(info, "currentRatio")
    if cr is not None:
        results.append({"name": "유동비율 >= 200%", "passed": cr >= 2.0, "value": f"{cr*100:.0f}%"})
    else:
        results.append({"name": "유동비율 >= 200%", "passed": None, "value": "데이터 없음"})

    dy = safe_get(info, "dividendYield")
    if dy is not None:
        results.append({"name": "배당 지급", "passed": dy > 0, "value": f"{dy*100:.2f}%"})
    else:
        results.append({"name": "배당 지급", "passed": None, "value": "데이터 없음"})

    return results


def evaluate_lynch(info: dict, sector_t: dict) -> list[dict]:
    results = []
    peg = safe_get(info, "pegRatio")
    if peg is not None:
        results.append({"name": "PEG < 1", "passed": 0 < peg < 1, "value": f"{peg:.2f}"})
    else:
        results.append({"name": "PEG < 1", "passed": None, "value": "데이터 없음"})

    rg = safe_get(info, "revenueGrowth")
    if rg is not None:
        results.append({"name": "매출 성장률 > 10%", "passed": rg > 0.10, "value": f"{rg*100:.1f}%"})
    else:
        results.append({"name": "매출 성장률 > 10%", "passed": None, "value": "데이터 없음"})

    eg = safe_get(info, "earningsGrowth")
    if eg is not None:
        results.append({"name": "EPS 성장률 > 15%", "passed": eg > 0.15, "value": f"{eg*100:.1f}%"})
    else:
        results.append({"name": "EPS 성장률 > 15%", "passed": None, "value": "데이터 없음"})

    de = safe_get(info, "debtToEquity")
    if de is not None:
        results.append({"name": "부채비율 <= 80%", "passed": de <= 80, "value": f"{de:.1f}%"})
    else:
        results.append({"name": "부채비율 <= 80%", "passed": None, "value": "데이터 없음"})

    inst = safe_get(info, "heldPercentInstitutions")
    if inst is not None:
        results.append({"name": "기관 보유 < 60% (아직 안 알려진 종목)", "passed": inst < 0.60, "value": f"{inst*100:.1f}%"})
    else:
        results.append({"name": "기관 보유 < 60%", "passed": None, "value": "데이터 없음"})

    return results


def evaluate_fisher(info: dict, sector_t: dict) -> list[dict]:
    results = []
    rg = safe_get(info, "revenueGrowth")
    if rg is not None:
        results.append({"name": "매출 성장률 > 10%", "passed": rg > 0.10, "value": f"{rg*100:.1f}%"})
    else:
        results.append({"name": "매출 성장률 > 10%", "passed": None, "value": "데이터 없음"})

    om = safe_get(info, "operatingMargins")
    if om is not None:
        results.append({"name": f"영업이익률 >= {sector_t['om_min']*100:.0f}% (섹터 기준)",
                        "passed": om >= sector_t['om_min'], "value": f"{om*100:.1f}%"})
    else:
        results.append({"name": "영업이익률 (섹터 기준)", "passed": None, "value": "데이터 없음"})

    gm = safe_get(info, "grossMargins")
    if gm is not None:
        results.append({"name": f"매출총이익률 >= {sector_t['gm_min']*100:.0f}% (R&D 여력)",
                        "passed": gm >= sector_t['gm_min'], "value": f"{gm*100:.1f}%"})
    else:
        results.append({"name": "매출총이익률 (섹터 기준)", "passed": None, "value": "데이터 없음"})

    pm = safe_get(info, "profitMargins")
    if pm is not None:
        results.append({"name": f"순이익률 >= {sector_t['pm_min']*100:.0f}% (섹터 기준)",
                        "passed": pm >= sector_t['pm_min'], "value": f"{pm*100:.1f}%"})
    else:
        results.append({"name": "순이익률 (섹터 기준)", "passed": None, "value": "데이터 없음"})

    price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice")
    target = safe_get(info, "targetMeanPrice")
    if price and target and price > 0:
        upside = (target - price) / price
        results.append({"name": "애널리스트 목표가 10%+ 상승여력", "passed": upside > 0.10, "value": f"{upside*100:.1f}%"})
    else:
        results.append({"name": "애널리스트 목표가 10%+ 상승여력", "passed": None, "value": "데이터 없음"})

    return results


def resolve_ticker(query: str) -> str | None:
    q = query.strip()
    if q.isascii() and q.upper() == q and q.replace("-", "").replace(".", "").isalpha() and len(q) <= 6:
        return q.upper()
    if q.isdigit() and len(q) == 6:
        return q + ".KS"
    if q in KR_STOCKS:
        return KR_STOCKS[q][0]
    if q in US_STOCKS_KR:
        return US_STOCKS_KR[q]
    for name, (ticker, _) in KR_STOCKS.items():
        if q in name:
            return ticker
    for kr_name, ticker in US_STOCKS_KR.items():
        if q in kr_name:
            return ticker
    try:
        encoded = urllib.parse.quote(q)
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded}&quotesCount=1&newsCount=0&listsCount=0"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json_lib.loads(resp.read())
        quotes = data.get("quotes", [])
        if quotes:
            return quotes[0]["symbol"]
    except Exception:
        pass
    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/sw.js")
def sw_js_root():
    # Service Worker는 스코프 문제로 루트에서 서빙
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@app.route("/install")
def install_guide():
    return render_template("install.html")


@app.route("/glossary")
def glossary():
    return render_template("glossary.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/api/search", methods=["GET"])
def search_stocks():
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify([])
    results = []
    kr_results = search_kr_stocks(q)
    results.extend(kr_results)
    try:
        encoded = urllib.parse.quote(q)
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded}&quotesCount=6&newsCount=0&listsCount=0"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json_lib.loads(resp.read())
        for item in data.get("quotes", []):
            symbol = item.get("symbol", "")
            if any(r["symbol"] == symbol for r in results):
                continue
            results.append({
                "symbol": symbol,
                "name": item.get("shortname", "") or item.get("longname", ""),
                "engName": item.get("longname", ""),
                "exchange": item.get("exchDisp", ""),
                "sector": item.get("sector", "") or item.get("industry", ""),
            })
    except Exception:
        pass
    return jsonify(results[:8])


@app.route("/api/analyze", methods=["POST"])
def analyze():
    body = request.get_json(force=True, silent=True)
    if body is None or not body.get("ticker"):
        try:
            raw_body = request.get_data() or b""
            body = json_lib.loads(raw_body.decode("utf-8", errors="replace") or "{}")
        except Exception:
            body = body or {}
    raw_query = (body.get("ticker") or "").strip()
    if not raw_query:
        return jsonify({"error": "종목명 또는 티커를 입력해주세요."}), 400

    ticker = resolve_ticker(raw_query)
    if ticker is None:
        ticker = raw_query.upper()

    data = get_stock_data(ticker)
    if data is None:
        error_type = detect_fetch_error_type(ticker)
        if error_type == "DATA_SOURCE_LIMITED":
            msg = "Yahoo Finance 데이터 제공이 일시 제한됐습니다. 2~3분 후 다시 시도해주세요. (한국 주식은 대체 데이터로 계속 사용 가능)"
            return jsonify({"error": msg, "type": error_type}), 503
        elif error_type == "DATA_SOURCE_DOWN":
            msg = "데이터 소스가 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해주세요."
            return jsonify({"error": msg, "type": error_type}), 503
        else:
            return jsonify({"error": f"'{raw_query}' 종목을 찾을 수 없습니다. 티커·종목명을 확인해주세요."}), 404

    info = data["info"]
    hist = data.get("hist")
    stock = data.get("stock")

    sector = safe_get(info, "sector", "N/A")
    sector_t = get_sector_thresholds(sector if sector != "N/A" else None)

    price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice", 0)
    market_cap = safe_get(info, "marketCap", 0)
    cap_str = f"${market_cap/1e9:.1f}B" if market_cap >= 1e9 else f"${market_cap/1e6:.0f}M"

    stock_info = {
        "name": safe_get(info, "longName", ticker),
        "sector": sector,
        "industry": safe_get(info, "industry", "N/A"),
        "price": f"{safe_get(info, 'currency', 'USD')} {price:,.2f}",
        "marketCap": cap_str,
        "logo": safe_get(info, "logo_url", ""),
    }

    is_kr = ticker.endswith(".KS") or ticker.endswith(".KQ")

    def _safe_call(fn, default, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            app.logger.warning(f"{fn.__name__} failed: {e}")
            return default

    def _merge_dart_into_history(hist: dict, dart: dict) -> dict:
        """DART 공시 재무를 history_data에 병합. 공시가 있는 연도는 DART 값 우선."""
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
        hist["source"] = "dart"
        return hist

    def _populate_info_from_dart(info: dict, dart: dict) -> None:
        """DART 최신 연도 값으로 info(yfinance 형식) 보강 — 한국 주식 전체 지표 활성화."""
        years = dart.get("years") or []
        if not years:
            return

        def _last(lst):
            for v in reversed(lst or []):
                if v is not None:
                    return v
            return None

        def _last_n(lst, n):
            vals = [v for v in (lst or []) if v is not None]
            return vals[-n:] if len(vals) >= n else vals

        rev = dart.get("revenue") or []
        ni = dart.get("net_income") or []
        oi = dart.get("operating_income") or []
        gp = dart.get("gross_profit") or []
        eq = dart.get("equity") or []
        assets = dart.get("total_assets") or []
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
            _set_if_missing("currentRatio", ca_l / cl_l)

        # YoY 성장률
        rev_vals = [v for v in rev if v is not None]
        if len(rev_vals) >= 2 and rev_vals[-2] > 0:
            _set_if_missing("revenueGrowth", (rev_vals[-1] - rev_vals[-2]) / rev_vals[-2])
        ni_vals = [v for v in ni if v is not None]
        if len(ni_vals) >= 2 and ni_vals[-2] != 0:
            _set_if_missing("earningsGrowth", (ni_vals[-1] - ni_vals[-2]) / abs(ni_vals[-2]))

    market_cache_key = f"market_regime:{is_kr}"
    market_data = cache.get(market_cache_key)
    if market_data is None:
        market_data = _safe_call(get_market_regime, {"available": False}, is_kr=is_kr)
        if market_data.get("available"):
            cache.set(market_cache_key, market_data, ttl=900)

    rs_data = _safe_call(calculate_rs_rating, {"available": False}, ticker, hist=hist)
    history_data = _safe_call(get_historical_metrics, {"available": False}, stock)

    # 한국 주식(.KS/.KQ)은 DART 공시 데이터로 재무 history 보강 (더 정확)
    if is_kr and dart_client.is_available():
        dart_fin = _safe_call(dart_client.fetch_financials, None, ticker, years=5)
        if dart_fin and dart_fin.get("years"):
            history_data = _merge_dart_into_history(history_data, dart_fin)
            info["_data_source_dart"] = True
            _populate_info_from_dart(info, dart_fin)

    quality_data = _safe_call(evaluate_earnings_quality, {"available": False}, stock, info)
    fair_value = _safe_call(calculate_fair_value, {"available": False}, info, stock, history_data)

    investors = [
        {"name": "워렌 버핏", "label": "워렌 버핏이라면?", "sub": "가치투자", "icon": "buffett",
         "criteria": evaluate_buffett(info, sector_t, history_data=history_data, fair_value=fair_value)},
        {"name": "벤저민 그레이엄", "label": "벤저민 그레이엄이라면?", "sub": "안전마진", "icon": "graham", "criteria": evaluate_graham(info, sector_t)},
        {"name": "피터 린치", "label": "피터 린치라면?", "sub": "성장주", "icon": "lynch", "criteria": evaluate_lynch(info, sector_t)},
        {"name": "윌리엄 오닐", "label": "윌리엄 오닐이라면?", "sub": "CAN SLIM", "icon": "oneil",
         "criteria": evaluate_oneil(info, ticker=ticker, hist=hist, rs_data=rs_data, market_data=market_data)},
        {"name": "필립 피셔", "label": "필립 피셔라면?", "sub": "장기성장", "icon": "fisher", "criteria": evaluate_fisher(info, sector_t)},
    ]

    total_yes, total_count = 0, 0
    for inv in investors:
        yes = sum(1 for c in inv["criteria"] if c["passed"] is True)
        count = sum(1 for c in inv["criteria"] if c["passed"] is not None)
        inv["yes"] = yes
        inv["total"] = count
        inv["rate"] = round(yes / count * 100) if count > 0 else 0
        total_yes += yes
        total_count += count

        # 버핏 전용 엄격 등급 (9기준 중 통과 수 기반 — %가 아닌 절대값)
        if inv["name"] == "워렌 버핏":
            inv["strict_grade"] = buffett_strict_grade(yes, count)

    overall_rate = round(total_yes / total_count * 100) if total_count > 0 else 0
    if overall_rate >= 70:
        grade, grade_text = "A", "매우 우수"
    elif overall_rate >= 55:
        grade, grade_text = "B", "우수"
    elif overall_rate >= 40:
        grade, grade_text = "C", "보통"
    elif overall_rate >= 25:
        grade, grade_text = "D", "미흡"
    else:
        grade, grade_text = "F", "부적합"

    overall = {"yes": total_yes, "total": total_count, "rate": overall_rate, "grade": grade, "gradeText": grade_text}

    fear_greed = _safe_call(evaluate_fear_greed, {"score": None, "label": "데이터 부족", "indicators": []}, data)
    positions = _safe_call(evaluate_positions, {"short": [], "long": [], "sentiment": "중립", "sentimentDetail": ""}, data)
    # 옵션 체인은 느리므로 별도 엔드포인트(/api/options)로 분리 — 탭 클릭 시 로드
    options = {"available": None, "lazy": True}

    verdict = _safe_call(generate_verdict, {"decision": "관망", "color": "yellow", "reasons": [], "warnings": [], "confidence": "low"},
                         overall, rs_data, market_data, fair_value, quality_data, fear_greed)

    return jsonify({
        "stock": stock_info,
        "ticker": ticker,
        "sectorThresholds": sector_t,
        "marketRegime": market_data,
        "rsRating": rs_data,
        "history": history_data,
        "quality": quality_data,
        "fairValue": fair_value,
        "verdict": verdict,
        "fearGreed": fear_greed,
        "positions": positions,
        "options": options,
        "investors": investors,
        "overall": overall,
        "dataWarnings": info.get("_data_warnings", []),
    })


@app.route("/api/options", methods=["POST"])
def analyze_options():
    body = request.get_json(force=True, silent=True)
    if body is None or not body.get("ticker"):
        try:
            raw_body = request.get_data() or b""
            body = json_lib.loads(raw_body.decode("utf-8", errors="replace") or "{}")
        except Exception:
            body = body or {}
    raw_query = (body.get("ticker") or "").strip()
    if not raw_query:
        return jsonify({"available": False, "error": "티커 필요"}), 400
    ticker = resolve_ticker(raw_query) or raw_query.upper()
    data = get_stock_data(ticker)
    if data is None:
        return jsonify({"available": False, "error": "종목을 찾을 수 없습니다"}), 404
    try:
        return jsonify(evaluate_options(data))
    except Exception as e:
        app.logger.exception("options fail")
        return jsonify({"available": False, "error": str(e)[:200]}), 500


@app.route("/api/most_active")
def api_most_active():
    cache_key = "most_active:v1"
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return jsonify(cached_result)
    try:
        result = get_most_active()
        cache.set(cache_key, result, ttl=900)  # 15분 캐시
        return jsonify(result)
    except Exception as e:
        app.logger.exception("most_active fail")
        return jsonify({"us": [], "kr": [], "error": str(e)[:200]}), 500


@app.route("/api/cache/stats")
def cache_stats():
    return jsonify(cache.stats())


@app.route("/api/debug/echo", methods=["POST"])
def debug_echo():
    """body가 어떻게 들어오는지 확인."""
    raw_bytes = request.get_data()
    raw_text = raw_bytes.decode("utf-8", errors="replace")
    body_json = request.get_json(force=True, silent=True)
    try:
        manual = json_lib.loads(raw_text or "{}")
    except Exception as e:
        manual = {"parse_error": str(e)}
    from kr_stocks import search_kr_stocks, KR_STOCKS
    ticker_in = (body_json or {}).get("ticker") or manual.get("ticker") or ""
    # kr_stocks 매핑 테스트
    mapped = KR_STOCKS.get(ticker_in)
    search_hit = search_kr_stocks(ticker_in)[:3] if ticker_in else []
    return jsonify({
        "content_type": request.content_type,
        "raw_bytes_len": len(raw_bytes),
        "raw_bytes_hex": raw_bytes.hex()[:200],
        "raw_text": raw_text[:300],
        "body_json_parsed": body_json,
        "manual_parsed": manual,
        "ticker_in": ticker_in,
        "ticker_in_len": len(ticker_in),
        "ticker_in_codepoints": [hex(ord(c)) for c in ticker_in[:20]],
        "kr_stocks_direct": mapped,
        "search_results": search_hit,
    })


@app.route("/api/debug/dart")
def dart_debug():
    """DART 연결 진단 (키 자체는 절대 노출 안 함)."""
    key = os.getenv("DART_API_KEY") or ""
    info = {
        "env_key_set": bool(key),
        "env_key_len": len(key),
        "env_key_prefix": key[:4] + "..." if key else "",
        "is_available": dart_client.is_available(),
    }
    try:
        m = dart_client._load_corp_map()
        info["corp_map_size"] = len(m)
        info["sample_samsung"] = m.get("005930", "NOT_FOUND")
    except Exception as e:
        info["corp_map_error"] = str(e)[:200]
    return jsonify(info)


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=debug, host="0.0.0.0", port=port)
