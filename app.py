"""유명 투자자 기준 주식 스크리너 - Flask 웹앱 (개선판)."""

import os
import math
import time
import urllib.request
import urllib.parse
import json as json_lib
from collections import defaultdict

from flask import Flask, render_template, request, jsonify
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

app = Flask(__name__)
app.json = SafeJSONProvider(app)

RATE_LIMIT_PER_MIN = 30
_rate_bucket: dict = defaultdict(list)


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


@cached(ttl=300)
def get_stock_data(ticker: str) -> dict | None:
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        if not info or info.get("regularMarketPrice") is None:
            return None

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
def evaluate_buffett(info: dict, sector_t: dict) -> list[dict]:
    results = []
    roe = safe_get(info, "returnOnEquity")
    if roe is not None:
        note = info.get("_roe_note", "")
        val_str = f"{roe*100:.1f}%" + (f" ({note})" if note else "")
        results.append({"name": f"ROE >= {sector_t['roe_min']*100:.0f}% (섹터 기준)",
                        "passed": roe >= sector_t['roe_min'] and note != "자본잠식",
                        "value": val_str})
    else:
        results.append({"name": "ROE (섹터 기준)", "passed": None, "value": "데이터 없음"})

    de = safe_get(info, "debtToEquity")
    if de is not None:
        note = info.get("_de_note", "")
        val_str = f"{de:.1f}%" + (f" ({note})" if note else "")
        results.append({"name": f"부채비율 <= {sector_t['de_max']}% (섹터 기준)",
                        "passed": de <= sector_t['de_max'] and de > 0 and note != "자본잠식",
                        "value": val_str})
    else:
        results.append({"name": "부채비율 (섹터 기준)", "passed": None, "value": "데이터 없음"})

    om = safe_get(info, "operatingMargins")
    if om is not None:
        results.append({"name": f"영업이익률 >= {sector_t['om_min']*100:.0f}% (섹터 기준)",
                        "passed": om >= sector_t['om_min'], "value": f"{om*100:.1f}%"})
    else:
        results.append({"name": "영업이익률 (섹터 기준)", "passed": None, "value": "데이터 없음"})

    rg = safe_get(info, "revenueGrowth")
    if rg is not None:
        results.append({"name": "매출 성장 중", "passed": rg > 0, "value": f"{rg*100:.1f}%"})
    else:
        results.append({"name": "매출 성장 중", "passed": None, "value": "데이터 없음"})

    fcf = safe_get(info, "freeCashflow")
    if fcf is not None:
        results.append({"name": "FCF 양수", "passed": fcf > 0, "value": f"${fcf/1e9:.2f}B"})
    else:
        results.append({"name": "FCF 양수", "passed": None, "value": "데이터 없음"})

    return results


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
    raw_query = request.json.get("ticker", "").strip()
    if not raw_query:
        return jsonify({"error": "종목명 또는 티커를 입력해주세요."}), 400

    ticker = resolve_ticker(raw_query)
    if ticker is None:
        ticker = raw_query.upper()

    data = get_stock_data(ticker)
    if data is None:
        return jsonify({"error": f"'{raw_query}' 종목을 찾을 수 없습니다."}), 404

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

    market_cache_key = f"market_regime:{is_kr}"
    market_data = cache.get(market_cache_key)
    if market_data is None:
        market_data = _safe_call(get_market_regime, {"available": False}, is_kr=is_kr)
        if market_data.get("available"):
            cache.set(market_cache_key, market_data, ttl=900)

    rs_data = _safe_call(calculate_rs_rating, {"available": False}, ticker, hist=hist)
    history_data = _safe_call(get_historical_metrics, {"available": False}, stock)
    quality_data = _safe_call(evaluate_earnings_quality, {"available": False}, stock, info)
    fair_value = _safe_call(calculate_fair_value, {"available": False}, info, stock, history_data)

    investors = [
        {"name": "워렌 버핏", "sub": "가치투자", "icon": "buffett", "criteria": evaluate_buffett(info, sector_t)},
        {"name": "벤저민 그레이엄", "sub": "안전마진", "icon": "graham", "criteria": evaluate_graham(info, sector_t)},
        {"name": "피터 린치", "sub": "성장주", "icon": "lynch", "criteria": evaluate_lynch(info, sector_t)},
        {"name": "윌리엄 오닐", "sub": "CAN SLIM", "icon": "oneil",
         "criteria": evaluate_oneil(info, ticker=ticker, hist=hist, rs_data=rs_data, market_data=market_data)},
        {"name": "필립 피셔", "sub": "장기성장", "icon": "fisher", "criteria": evaluate_fisher(info, sector_t)},
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
    raw_query = request.json.get("ticker", "").strip()
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


@app.route("/api/cache/stats")
def cache_stats():
    return jsonify(cache.stats())


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=debug, host="0.0.0.0", port=port)
