"""유명 투자자 기준 주식 스크리너 - Flask 웹앱 (개선판)."""

import os
import math
import time
import hmac
import ipaddress
import urllib.request
import urllib.parse
import json as json_lib
from collections import defaultdict

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Sentry 에러 추적 (SENTRY_DSN 환경변수 있을 때만 활성)
_SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.05,           # 트레이스 5%만 (비용 통제)
            profiles_sample_rate=0.0,
            send_default_pii=False,            # IP·이메일 등 미전송
            environment=os.getenv("RENDER_ENV", "production"),
            release=os.getenv("RENDER_GIT_COMMIT", "unknown")[:7],
            # 자주 발생하는 무해 에러는 보내지 않음 (노이즈 줄이기)
            ignore_errors=["KeyboardInterrupt", "SystemExit"],
        )
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

from kr_stocks import search_kr_stocks, KR_STOCKS, US_STOCKS_KR, get_kr_description, get_us_description, sector_kr
from data.fx import get_usd_krw
from data.cache import cache, cached
from data.fetcher import fetch_stock_data, detect_fetch_error_type
from data import dart_client
from data import krx_client
from data import sec_client
from data import kr_listing
from data import naver_news
from data import daily_briefing
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
from analysis.evaluators import (
    safe_get, fmt_money,
    evaluate_positions,
    evaluate_buffett, buffett_strict_grade,
    evaluate_graham, lynch_category, evaluate_lynch, evaluate_fisher,
)

app = Flask(__name__)
app.json = SafeJSONProvider(app)

# Reverse proxy 신뢰 — Railway/Render의 X-Forwarded-* 헤더를 정상 처리.
# x_for=1: 신뢰 가능한 proxy 1단계만(가장 마지막 hop) 사용 → 클라이언트 X-Forwarded-For 위조 차단.
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_port=0)

# Rate limit — 메서드/엔드포인트별 차등 적용
RATE_LIMIT_POST_PER_MIN = 20   # 분석·옵션·KRX 같은 무거운 POST: 분당 20회
RATE_LIMIT_GET_PER_MIN = 60    # 검색·캐시 통계 같은 가벼운 GET: 분당 60회
RATE_LIMIT_BURST_PER_10S = 8   # 10초 내 8회 초과 시 일시 차단 (봇 폭주 방지)
_rate_bucket: dict = defaultdict(list)
_rate_bucket_burst: dict = defaultdict(list)
_RATE_BUCKET_MAX = 10000       # IP 엔트리 한도 — 봇 다중 IP 폭주 시 RAM 폭주 방지


CANONICAL_HOST = "stockinto.com"
REDIRECT_HOSTS = {"stockinto.co.kr", "www.stockinto.co.kr", "www.stockinto.com"}


# 모니터링 봇 시그니처 — GA4·AdSense 트래픽 오염 방지용
# UptimeRobot 5분 핑이 일일 288회 들어와서 통계가 봇 트래픽으로 도배되는 문제 차단
_MONITORING_BOT_UAS = ("uptimerobot", "uptime-kuma", "pingdom", "statuscake")


@app.context_processor
def inject_bot_flag():
    """모든 템플릿에 is_bot 변수 주입 — 추적 스크립트 조건부 렌더링용."""
    ua = (request.headers.get("User-Agent") or "").lower()
    is_bot = any(sig in ua for sig in _MONITORING_BOT_UAS)
    return {"is_bot": is_bot}


@app.before_request
def _canonical_redirect():
    """`.co.kr` 및 `www.` 접속을 `stockinto.com`으로 301 리다이렉트 (SEO 최적화)."""
    host = (request.host or "").lower().split(":")[0]
    if host in REDIRECT_HOSTS:
        path = request.full_path if request.query_string else request.path
        path = path.rstrip("?")
        return redirect(f"https://{CANONICAL_HOST}{path}", code=301)
    return None


def _is_local_or_private_ip() -> bool:
    """클라이언트 IP가 loopback/사설 대역인지 — 디버그·진단 게이팅용."""
    try:
        ip = ipaddress.ip_address(request.remote_addr or "")
        return ip.is_loopback or ip.is_private
    except (ValueError, TypeError):
        return False


def _diag_enabled() -> bool:
    """진단 모드 — STOCKINTO_DEBUG=1 + 로컬/사설 IP에서만 (운영 실수 방어)."""
    return os.getenv("STOCKINTO_DEBUG") == "1" and _is_local_or_private_ip()


@app.errorhandler(500)
def _handle_500(e):
    if request.path.startswith("/api/"):
        app.logger.exception("API 500 error")
        msg = "서버에 일시적인 문제가 발생했습니다. 잠시 후 다시 시도해주세요."
        if _diag_enabled():
            import traceback
            return jsonify({"error": msg, "_debug": traceback.format_exc()[:2500]}), 500
        return jsonify({"error": msg}), 500
    return "Internal Server Error", 500


@app.errorhandler(Exception)
def _handle_exc(e):
    # Flask/Werkzeug HTTP 예외 (404, 400, 405 등)는 그대로 통과 — 정상 라우팅 처리
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    if request.path.startswith("/api/"):
        app.logger.exception("API exception")
        if _diag_enabled():
            import traceback
            return jsonify({
                "error": "요청 처리 중 오류가 발생했습니다.",
                "_debug": f"{type(e).__name__}: {str(e)[:500]}",
                "_tb": traceback.format_exc()[:2500],
            }), 500
        # 운영에선 내부 정보 절대 노출 금지 — 일반화된 메시지만 반환
        return jsonify({"error": "요청 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}), 500
    raise e


def _prune_rate_buckets(now: float) -> None:
    """오래된 엔트리 정리 — IP 엔트리가 한도 초과 시 만료된 IP부터 제거."""
    if len(_rate_bucket) > _RATE_BUCKET_MAX:
        cutoff = now - 60
        for ip in [ip for ip, ts in _rate_bucket.items() if not ts or max(ts) < cutoff]:
            _rate_bucket.pop(ip, None)
    if len(_rate_bucket_burst) > _RATE_BUCKET_MAX:
        cutoff = now - 10
        for ip in [ip for ip, ts in _rate_bucket_burst.items() if not ts or max(ts) < cutoff]:
            _rate_bucket_burst.pop(ip, None)


@app.before_request
def _rate_limit():
    """3중 rate limit: 분당(메서드별) + 10초 burst.

    봇·폭주 방어 강화:
    - POST는 분당 20회 (분석은 무거우니 엄격)
    - GET은 분당 60회 (검색은 가벼우니 느슨)
    - 10초 안 8회 초과는 모든 요청 일시 429 (봇 폭주 차단)
    - ProxyFix가 X-Forwarded-For의 마지막 신뢰 hop을 remote_addr로 세팅 → 위조 불가
    """
    if not request.path.startswith("/api/"):
        return None
    ip = request.remote_addr or "unknown"
    now = time.time()
    _prune_rate_buckets(now)

    # 1) Burst 체크 (10초)
    burst = [t for t in _rate_bucket_burst[ip] if now - t < 10]
    if len(burst) >= RATE_LIMIT_BURST_PER_10S:
        _rate_bucket_burst[ip] = burst
        return jsonify({"error": "잠시 너무 많은 요청 — 5초 후 다시 시도."}), 429

    # 2) 분당 체크 (메서드별)
    bucket = [t for t in _rate_bucket[ip] if now - t < 60]
    limit = RATE_LIMIT_POST_PER_MIN if request.method == "POST" else RATE_LIMIT_GET_PER_MIN
    if len(bucket) >= limit:
        _rate_bucket[ip] = bucket
        return jsonify({"error": "요청이 너무 많습니다. 1분 뒤 다시 시도해주세요."}), 429

    bucket.append(now)
    burst.append(now)
    _rate_bucket[ip] = bucket
    _rate_bucket_burst[ip] = burst
    return None


# 허용된 Origin (CSRF 차단 — 외부 도메인 fetch 공격 방지)
import re as _re_origin
_ALLOWED_ORIGINS = {
    "https://stockinto.com",
    "https://www.stockinto.com",
    "https://stockinto.co.kr",
    "https://www.stockinto.co.kr",
    "https://stock-screener-1-mgkv.onrender.com",
    # Railway 임시 URL — 도메인 전환 후엔 제거 권장
    "https://web-production-2c5e2.up.railway.app",
}
# Railway 임시 도메인 패턴 자동 허용 (web-production-XXXX.up.railway.app)
# 도메인 전환 후 이 줄 + 위 임시 URL 두 줄 모두 제거 가능
_RAILWAY_TEMP_PATTERN = _re_origin.compile(r"^https://[\w\-]+\.up\.railway\.app$")
# 환경변수 ALLOWED_ORIGINS_EXTRA로 추가 origin도 콤마구분 등록 가능
_extra = (os.getenv("ALLOWED_ORIGINS_EXTRA") or "").strip()
if _extra:
    for o in _extra.split(","):
        o = o.strip().rstrip("/")
        if o:
            _ALLOWED_ORIGINS.add(o)


def _is_origin_allowed(origin: str) -> bool:
    """Origin 허용 여부 — 화이트리스트 또는 Railway 임시 URL 패턴."""
    if not origin:
        return False
    o = origin.rstrip("/")
    if o in _ALLOWED_ORIGINS:
        return True
    if _RAILWAY_TEMP_PATTERN.match(o):
        return True
    return False


@app.before_request
def _csrf_origin_check():
    """POST API 요청은 Origin/Referer가 자기 도메인이어야 함 (CSRF 차단).

    검사 순서: 화이트리스트 + Railway 임시 도메인 패턴 모두 허용.
    """
    if request.method != "POST" or not request.path.startswith("/api/"):
        return None
    origin = request.headers.get("Origin", "")
    referer = request.headers.get("Referer", "")
    # Origin 검사 우선, 없으면 Referer로 폴백
    if origin:
        if not _is_origin_allowed(origin):
            return jsonify({"error": "잘못된 요청 출처입니다."}), 403
    elif referer:
        # Referer는 path까지 포함되니 origin 부분만 추출해서 비교
        try:
            from urllib.parse import urlparse
            p = urlparse(referer)
            ref_origin = f"{p.scheme}://{p.netloc}"
            if not _is_origin_allowed(ref_origin):
                return jsonify({"error": "잘못된 요청 출처입니다."}), 403
        except Exception:
            return jsonify({"error": "잘못된 요청 출처입니다."}), 403
    # Origin·Referer 둘 다 없는 경우는 허용 (curl·서버사이드 호출 등)
    return None


@app.after_request
def _security_headers(resp):
    """5종 보안 헤더 — 클릭재킹·MIME 스니핑·HTTPS 다운그레이드·Referer 누출·CSP Report-Only.

    CSP는 Report-Only 모드 — 위반은 차단하지 않고 콘솔에만 기록.
    리팩터 3단계 후 인라인 <script>·onclick 모두 제거됨 → 'script-src self' 가능.
    inline style="..." 233건 잔재 → 'style-src unsafe-inline' 임시 허용 (다음 정리 대상).
    """
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    # CSP Report-Only — 차단 X, 위반만 콘솔 로그 → 며칠 모니터링 후 enforce 전환
    resp.headers.setdefault("Content-Security-Policy-Report-Only", (
        "default-src 'self'; "
        "script-src 'self' "
        "https://cdn.jsdelivr.net https://s3.tradingview.com "
        "https://www.googletagmanager.com https://www.google-analytics.com "
        "https://pagead2.googlesyndication.com https://*.googlesyndication.com "
        "https://*.adtrafficquality.google; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https: blob:; "
        "font-src 'self' data: https://cdn.jsdelivr.net; "
        "connect-src 'self' https://www.google-analytics.com https://*.google-analytics.com "
        "https://*.googlesyndication.com https://*.adtrafficquality.google "
        "https://stats.g.doubleclick.net; "
        "frame-src https://s.tradingview.com https://www.tradingview.com "
        "https://*.tradingview-widget.com https://*.googlesyndication.com "
        "https://*.doubleclick.net; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    ))
    return resp


# evaluators 함수들은 analysis/evaluators.py로 이동 (3일차 분리)


@cached(ttl=7200)  # 2시간 캐시 — "시세 15분 지연" UI 표기와 일치, Yahoo 호출 4배 절감
def get_stock_data(ticker: str) -> dict | None:
    """yfinance·FDR 통합 fetch + 2시간 캐시. 분석 핵심 진입점."""
    fetched = fetch_stock_data(ticker)
    if fetched is None:
        return None
    return fetched



import re

# 입력 검증 — 안전한 종목 검색어만 허용 (SSRF·Injection 차단)
# 허용: 영문, 숫자, 한글, 공백, 점, 하이픈. 길이 1~30
_SAFE_QUERY_RE = re.compile(r"^[\w가-힣\.\-\s]{1,30}$", re.UNICODE)


def is_safe_query(query: str) -> bool:
    if not query or len(query) > 30:
        return False
    return bool(_SAFE_QUERY_RE.match(query))


def resolve_ticker(query: str) -> str | None:
    q = query.strip()
    if q.isascii() and q.upper() == q and q.replace("-", "").replace(".", "").isalpha() and len(q) <= 6:
        return q.upper()
    if q.isdigit() and len(q) == 6:
        # 6자리 숫자만 입력 시 KOSPI 우선 → 없으면 KOSDAQ
        full_kospi = q + ".KS"
        full_kosdaq = q + ".KQ"
        # KRX 전체 리스트에서 정확한 거래소 확인
        for item in kr_listing.get_all_listings():
            if item["symbol"] == full_kospi:
                return full_kospi
            if item["symbol"] == full_kosdaq:
                return full_kosdaq
        return full_kospi  # 폴백
    # 1) 친근 별명 매핑 (89개)
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
    # 2) KRX 전체 리스트 (~2,500개) 정식 종목명 매칭
    kr_match = kr_listing.find_by_name(q)
    if kr_match:
        return kr_match
    # 3) Yahoo 검색 fallback (미국 종목·해외 ETF 등)
    try:
        encoded = urllib.parse.quote(q)
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded}&quotesCount=1&newsCount=0&listsCount=0"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json_lib.loads(resp.read())
        quotes = data.get("quotes", [])
        if quotes:
            return quotes[0]["symbol"]
    except Exception as e:
        app.logger.debug(f"Yahoo search resolve failed for '{q}': {type(e).__name__}")
    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/sw.js")
def sw_js_root():
    # Service Worker는 스코프 문제로 루트에서 서빙
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@app.route("/ads.txt")
def ads_txt():
    """Google AdSense ads.txt — 광고 사기 방지 표준."""
    return send_from_directory("static", "ads.txt", mimetype="text/plain")


@app.route("/robots.txt")
def robots_txt():
    return send_from_directory("static", "robots.txt", mimetype="text/plain")


@app.route("/favicon.ico")
def favicon():
    """루트 favicon — 구글·네이버 검색 결과용. 정적 캐시 1년."""
    resp = send_from_directory("static", "favicon.ico", mimetype="image/x-icon")
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


@app.route("/sitemap.xml")
def sitemap_xml():
    """정적 페이지 + 인기 종목 100여개 동적 sitemap 생성."""
    static_pages = [
        ("/", "daily", "1.0"),
        ("/about", "monthly", "0.9"),
        ("/glossary", "weekly", "0.8"),
        ("/briefing", "daily", "0.9"),
        ("/learn/buffett-criteria", "monthly", "0.85"),
        ("/learn/dcf-guide", "monthly", "0.85"),
        ("/picks/buffett-style", "weekly", "0.85"),
        ("/picks/dividend-aristocrats", "weekly", "0.85"),
        # 영어 페이지 (i18n Phase 1)
        ("/en/", "daily", "0.9"),
        ("/en/about", "monthly", "0.8"),
        ("/en/learn/buffett-criteria", "monthly", "0.8"),
        ("/en/learn/dcf-guide", "monthly", "0.8"),
        ("/en/picks/buffett-style", "weekly", "0.8"),
        ("/en/picks/dividend-aristocrats", "weekly", "0.8"),
        ("/install", "monthly", "0.7"),
        ("/contact", "monthly", "0.6"),
        ("/terms", "yearly", "0.4"),
        ("/privacy", "yearly", "0.4"),
    ]
    # 인기 종목 (한국 50개 + 미국 50개)
    pop_us = ["AAPL","MSFT","GOOGL","AMZN","META","TSLA","NVDA","AMD","INTC","NFLX",
              "JPM","BAC","V","MA","DIS","KO","PEP","WMT","COST","HD","NKE","SBUX","MCD",
              "PG","JNJ","UNH","XOM","CVX","BA","CAT","GE","F","GM","T","VZ","CRM","ORCL",
              "ADBE","CSCO","IBM","QCOM","TXN","BRK-B","BLK","GS","MS","C","WFC","PYPL","SQ"]
    pop_kr = []
    for kr_name, (ticker, _eng) in list(KR_STOCKS.items())[:50]:
        pop_kr.append(ticker)

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, freq, prio in static_pages:
        parts.append(f'  <url><loc>https://stockinto.com{path}</loc><changefreq>{freq}</changefreq><priority>{prio}</priority></url>')
    for tk in pop_us + pop_kr:
        parts.append(f'  <url><loc>https://stockinto.com/stock/{tk}</loc><changefreq>weekly</changefreq><priority>0.7</priority></url>')
    parts.append('</urlset>')
    from flask import Response
    return Response("\n".join(parts), mimetype="application/xml")


@app.route("/stock/<ticker>")
def stock_detail(ticker: str):
    """종목별 정적 SEO 페이지 — `/stock/AAPL`, `/stock/005930.KS`.

    프론트는 메인 페이지 그대로 자동 검색. 차이점은 SEO 메타가 종목 특화.
    """
    if not ticker or len(ticker) > 15:
        return redirect("/", code=302)
    # 안전한 형식만 허용 (영문·숫자·점·하이픈)
    if not re.match(r"^[A-Za-z0-9.\-]{1,15}$", ticker):
        return redirect("/", code=302)
    ticker = ticker.upper()
    # 한국 명칭 매핑이 있으면 사용
    display_name = ticker
    for kr_name, (tk, eng_name) in KR_STOCKS.items():
        if tk == ticker:
            display_name = f"{kr_name} ({ticker})"
            break
    return render_template("index.html", stock_ticker=ticker, stock_name=display_name)


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


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/about")
def about():
    return render_template("about.html")


# ===== 학습 가이드 (장문 SEO 콘텐츠) =====
LEARN_TEMPLATES = {
    "buffett-criteria": "learn_buffett.html",
    "dcf-guide": "learn_dcf.html",
}


@app.route("/learn/<topic>")
def learn_topic(topic: str):
    """장문 학습 가이드 — 봇·검색 친화 SEO 콘텐츠."""
    tpl = LEARN_TEMPLATES.get(topic)
    if not tpl:
        return redirect("/", code=302)
    return render_template(tpl)


# ===== 큐레이션 (종목 모음) =====
PICKS_TEMPLATES = {
    "buffett-style": "picks_buffett.html",
    "dividend-aristocrats": "picks_dividend.html",
}


@app.route("/picks/<topic>")
def picks_topic(topic: str):
    """종목 큐레이션 페이지 — 내부 링크 강화 + SEO."""
    tpl = PICKS_TEMPLATES.get(topic)
    if not tpl:
        return redirect("/", code=302)
    return render_template(tpl)


# ===== 영어 라우트 (i18n Phase 1) =====
# 분석 결과는 한국어 /stock/<ticker> 재사용 (Phase 1 타협).
# Phase 2에서 영어 종목 페이지·동적 분석 결과 영어화 예정.
EN_LEARN_TEMPLATES = {
    "buffett-criteria": "en/learn_buffett.html",
    "dcf-guide": "en/learn_dcf.html",
}
EN_PICKS_TEMPLATES = {
    "buffett-style": "en/picks_buffett.html",
    "dividend-aristocrats": "en/picks_dividend.html",
}


@app.route("/en/")
@app.route("/en")
def en_index():
    return render_template("en/index.html")


@app.route("/en/about")
def en_about():
    return render_template("en/about.html")


@app.route("/en/learn/<topic>")
def en_learn(topic: str):
    tpl = EN_LEARN_TEMPLATES.get(topic)
    if not tpl:
        return redirect("/en/", code=302)
    return render_template(tpl)


@app.route("/en/picks/<topic>")
def en_picks(topic: str):
    tpl = EN_PICKS_TEMPLATES.get(topic)
    if not tpl:
        return redirect("/en/", code=302)
    return render_template(tpl)


@app.route("/api/search", methods=["GET"])
def search_stocks():
    """검색 우선순위:
    1) 친근 별명 (KR_STOCKS 89개) — 정확 일치 + 부분 일치
    2) KRX 전체 상장 종목 (~2,500개) — 정식 종목명·코드 매칭
    3) Yahoo Finance 검색 — 미국·해외 ETF 등

    Yahoo amplification 방어 — 동일 쿼리 5분 캐시 (외부 API 부하 차단).
    """
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify([])
    # 입력 검증 — 비정상 문자열은 즉시 거절 (Yahoo 호출 방지)
    if len(q) > 30 or not is_safe_query(q):
        return jsonify([])

    cache_key = f"search:{q.lower()}"
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return jsonify(cached_result)

    results = []
    seen = set()

    def _add(item):
        if item["symbol"] not in seen:
            seen.add(item["symbol"])
            results.append(item)

    # 1) 친근 별명 매핑 우선
    for r in search_kr_stocks(q):
        _add(r)

    # 2) KRX 전체 종목 (정식 종목명) — 잡주·중소형주 커버
    if len(results) < 8:
        for r in kr_listing.search_listings(q, limit=8):
            _add(r)

    # 3) Yahoo 검색 — 미국·해외 (위 둘에서 8개 안 채워졌을 때)
    if len(results) < 6:
        try:
            encoded = urllib.parse.quote(q)
            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded}&quotesCount=6&newsCount=0&listsCount=0"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=5)
            data = json_lib.loads(resp.read())
            for item in data.get("quotes", []):
                symbol = item.get("symbol", "")
                if not symbol:
                    continue
                _add({
                    "symbol": symbol,
                    "name": item.get("shortname", "") or item.get("longname", ""),
                    "engName": item.get("longname", ""),
                    "exchange": item.get("exchDisp", ""),
                    "sector": item.get("sector", "") or item.get("industry", ""),
                })
        except Exception as e:
            app.logger.debug(f"Yahoo /api/search supplemental failed: {type(e).__name__}")

    final = results[:8]
    cache.set(cache_key, final, ttl=300)  # 5분 캐시 — Yahoo 부하 amplification 차단
    return jsonify(final)


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
    if not is_safe_query(raw_query):
        return jsonify({"error": "허용되지 않는 문자가 포함되었습니다. (영문·숫자·한글·점·하이픈만 허용)"}), 400

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
    cap_str = fmt_money(market_cap, info)

    currency = safe_get(info, "currency", "USD")
    if currency == "KRW":
        price_str = f"₩{price:,.0f}"
    else:
        price_str = f"${price:,.2f}"

    is_kr = ticker.endswith(".KS") or ticker.endswith(".KQ")

    # 사업 한 줄 설명 — 4단 폴백 (한국 매핑 → 미국 매핑 → 한국어 sector·industry → 영문)
    description = None
    if is_kr:
        description = get_kr_description(ticker)
    else:
        description = get_us_description(ticker)  # 신규: 미국 종목 한국어 매핑
    if not description:
        # 한국어 sector·industry 조합 폴백 (영문보다 친화적)
        ind = safe_get(info, "industry", "")
        sector_ko = sector_kr(sector) if sector and sector != "N/A" else ""
        if sector_ko and ind:
            description = f"{sector_ko} · {ind}"
        elif sector_ko:
            description = sector_ko
    if not description:
        # 마지막 폴백: yfinance longBusinessSummary 첫 문장 (영문)
        summary = safe_get(info, "longBusinessSummary", "") or ""
        if summary:
            first_sentence = summary.split(". ")[0].strip()
            if len(first_sentence) > 200:
                first_sentence = first_sentence[:200].rsplit(" ", 1)[0] + "..."
            description = first_sentence + "." if first_sentence and not first_sentence.endswith(".") else first_sentence

    # 미국 종목 시총에 원화 환산 추가 표시
    cap_str_full = cap_str
    if not is_kr and market_cap and market_cap > 0:
        try:
            usd_krw = get_usd_krw()
            krw_cap = market_cap * usd_krw
            if krw_cap >= 1e12:
                krw_str = f"₩{krw_cap/1e12:,.1f}조"
            elif krw_cap >= 1e8:
                krw_str = f"₩{krw_cap/1e8:,.0f}억"
            else:
                krw_str = f"₩{krw_cap:,.0f}"
            cap_str_full = f"{cap_str} (≈ {krw_str})"
        except Exception:
            pass  # 환율 실패해도 영향 없음

    stock_info = {
        "name": safe_get(info, "longName", ticker),
        "sector": sector_kr(sector) if sector and sector != "N/A" else sector,  # 섹터 한국어
        "sectorEn": sector,  # 영문 sector도 보존 (분석 로직용)
        "industry": safe_get(info, "industry", "N/A"),
        "price": price_str,
        "marketCap": cap_str_full,  # 원화 환산 포함
        "logo": safe_get(info, "logo_url", ""),
        "description": description or "",
    }

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

        # history EPS 채우기 (연도별 NI / 현재 shares)
        # (정확한 계산은 주식수 변동 고려해야 하지만, 근사치로 유용)

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
        # 배당 공시
        dart_div = _safe_call(dart_client.fetch_dividend, None, ticker)
        if dart_div:
            dps = dart_div.get("dps")
            y = dart_div.get("yield_pct")
            if dps is not None and info.get("dividendRate") is None:
                info["dividendRate"] = dps
            if y is not None and info.get("dividendYield") is None:
                info["dividendYield"] = y  # DART %를 그대로 저장 (yfinance 0.2.x+도 % 형식으로 통일)
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            if dps and price and price > 0 and info.get("payoutRatio") is None:
                eps = info.get("trailingEps")
                if eps and eps > 0:
                    info["payoutRatio"] = dps / eps

    # 미국 주식은 SEC EDGAR 공시 데이터로 재무 history 보강 (yfinance 부실 응답 보완)
    # SEC EDGAR = Public Domain (17 USC §105) → 상업 이용 무제한
    if (not is_kr) and sec_client.is_available():
        sec_fin = _safe_call(sec_client.fetch_financials, None, ticker, years=6)
        if sec_fin and sec_fin.get("years"):
            history_data = _merge_dart_into_history(history_data, sec_fin)  # 일반화된 병합
            info["_data_source_sec"] = True
            _populate_info_from_dart(info, sec_fin)  # 동일 인터페이스 — 미국에도 적용
            # SEC EPS·shares도 info에 보강
            eps_diluted = sec_fin.get("eps_diluted") or []
            shares = sec_fin.get("shares_outstanding") or []
            if eps_diluted:
                last_eps = next((v for v in reversed(eps_diluted) if v is not None), None)
                if last_eps and info.get("trailingEps") in (None, 0):
                    info["trailingEps"] = last_eps
            if shares:
                last_shares = next((v for v in reversed(shares) if v is not None), None)
                if last_shares and info.get("sharesOutstanding") in (None, 0):
                    info["sharesOutstanding"] = last_shares

        # SEC TTM 비율 — 미국 종목의 모든 비율 지표를 정부 공시 기반으로 정확화
        # yfinance 형식 변경(dividendYield 100배 등) 사고 영구 차단
        # D/E는 yfinance 정의(LT+ST debt만)가 더 정확해서 yfinance 우선 유지
        sec_ttm = _safe_call(sec_client.fetch_ttm_metrics, None, ticker)
        if sec_ttm:
            info["_sec_ttm"] = True

            def _safe_set(key, val, valid_check=lambda v: v is not None):
                if valid_check(val):
                    info[key] = val

            # 비율 지표 — SEC TTM이 yfinance 보다 정확 + 안정적
            if sec_ttm.get("roe") is not None:
                _safe_set("returnOnEquity", sec_ttm["roe"], lambda v: -2.0 <= v <= 5.0)
            if sec_ttm.get("operating_margin") is not None:
                _safe_set("operatingMargins", sec_ttm["operating_margin"], lambda v: -1.5 <= v <= 1.0)
            if sec_ttm.get("profit_margin") is not None:
                _safe_set("profitMargins", sec_ttm["profit_margin"], lambda v: -2.0 <= v <= 1.0)
            if sec_ttm.get("gross_margin") is not None:
                _safe_set("grossMargins", sec_ttm["gross_margin"], lambda v: -0.5 <= v <= 1.0)
            if sec_ttm.get("current_ratio") is not None:
                _safe_set("currentRatio", sec_ttm["current_ratio"], lambda v: 0.3 <= v <= 5.0)
            if sec_ttm.get("ttm_fcf") is not None:
                info["freeCashflow"] = sec_ttm["ttm_fcf"]
            if sec_ttm.get("ttm_revenue") is not None:
                info["totalRevenue"] = sec_ttm["ttm_revenue"]

            # PER/PBR/EPS/BPS — 자체 계산 (yfinance가 없거나 부정확할 때 보강)
            shares_out = info.get("sharesOutstanding") or sec_ttm.get("latest_shares")
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            ni_ttm = sec_ttm.get("ttm_net_income")
            equity = sec_ttm.get("latest_equity")
            if shares_out and shares_out > 0 and price and price > 0:
                if ni_ttm is not None and ni_ttm > 0:
                    eps = ni_ttm / shares_out
                    info["trailingEps"] = eps
                    info["trailingPE"] = price / eps
                if equity and equity > 0:
                    bps = equity / shares_out
                    info["bookValue"] = bps
                    info["priceToBook"] = price / bps

    # 한국 주식 KRX 수급 — lazy load (별도 /api/krx 엔드포인트, 탭 클릭 시 fetch)
    krx_data = {"available": None, "lazy": True} if (is_kr and krx_client.is_available()) else None

    quality_data = _safe_call(evaluate_earnings_quality, {"available": False}, stock, info)
    fair_value = _safe_call(calculate_fair_value, {"available": False}, info, stock, history_data)
    if isinstance(fair_value, dict):
        fair_value["currency"] = safe_get(info, "currency", "USD")

    # 5인 평가자 병렬 실행 — 각 함수는 순수 dict 처리라 GIL 풀림은 적지만,
    # 향후 외부 호출(예: KIS API) 추가 시 즉시 효과. 현재도 약간 단축.
    import concurrent.futures as _cf
    _eval_tasks = {
        "buffett":  lambda: evaluate_buffett(info, sector_t, history_data=history_data, fair_value=fair_value),
        "graham":   lambda: evaluate_graham(info, sector_t, history_data=history_data),
        "lynch":    lambda: evaluate_lynch(info, sector_t, history_data=history_data),
        "lynch_cat": lambda: lynch_category(info, history_data=history_data),
        "oneil":    lambda: evaluate_oneil(info, ticker=ticker, hist=hist, rs_data=rs_data, market_data=market_data),
        "fisher":   lambda: evaluate_fisher(info, sector_t, history_data=history_data),
    }
    _eval_results = {}
    with _cf.ThreadPoolExecutor(max_workers=6) as _ex:
        _futures = {_ex.submit(fn): name for name, fn in _eval_tasks.items()}
        for _f in _cf.as_completed(_futures, timeout=15):
            _name = _futures[_f]
            try:
                _eval_results[_name] = _f.result()
            except Exception:
                app.logger.exception(f"evaluator '{_name}' failed")
                _eval_results[_name] = [] if _name != "lynch_cat" else {"code": "UNCLASSIFIED", "label": "분류 불가", "desc": "오류"}

    investors = [
        {"name": "워렌 버핏", "label": "워렌 버핏이라면?", "sub": "가치투자", "icon": "buffett",
         "criteria": _eval_results.get("buffett", [])},
        {"name": "벤저민 그레이엄", "label": "벤저민 그레이엄이라면?", "sub": "안전마진", "icon": "graham",
         "criteria": _eval_results.get("graham", [])},
        {"name": "피터 린치", "label": "피터 린치라면?", "sub": "성장주", "icon": "lynch",
         "criteria": _eval_results.get("lynch", []),
         "category": _eval_results.get("lynch_cat", {"code": "UNCLASSIFIED", "label": "분류 불가", "desc": ""})},
        {"name": "윌리엄 오닐", "label": "윌리엄 오닐이라면?", "sub": "CAN SLIM", "icon": "oneil",
         "criteria": _eval_results.get("oneil", [])},
        {"name": "필립 피셔", "label": "필립 피셔라면?", "sub": "장기성장", "icon": "fisher",
         "criteria": _eval_results.get("fisher", [])},
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
    # 등급 = 5인 대가 기준 통과율 (참고용 점수, 매수·매도 권유 아님)
    if overall_rate >= 70:
        grade, grade_text = "A", "기준 통과율 매우 높음"
    elif overall_rate >= 55:
        grade, grade_text = "B", "기준 통과율 높음"
    elif overall_rate >= 40:
        grade, grade_text = "C", "기준 통과율 보통"
    elif overall_rate >= 25:
        grade, grade_text = "D", "기준 통과율 낮음"
    else:
        grade, grade_text = "F", "기준 통과율 매우 낮음"

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
        "krx": krx_data,
        "dataWarnings": info.get("_data_warnings", []),
        "dataMeta": _build_data_meta(info, ticker, is_kr, history_data),
    })


def _build_data_meta(info: dict, ticker: str, is_kr: bool, history_data: dict | None) -> dict:
    """응답 메타데이터 — 사용자가 데이터 시점·출처를 즉시 이해할 수 있게.

    법적 보호: 자본시장법상 정보 제공자임을 명시 + 시점 명확화 (조언 아님).
    """
    from datetime import datetime, timezone, timedelta
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
        from data.cache import cache as _cache
        cik = None
        try:
            from data.sec_client import _get_cik
            cik = _get_cik(ticker)
        except Exception:
            pass
        if cik:
            cached_ttm = _cache.get(f"sec_ttm_v1:{cik}")
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


@app.route("/briefing")
@app.route("/briefing/<date_str>")
def briefing_page(date_str=None):
    """일일 금융 브리핑 페이지 — 매일 자동 갱신.

    /briefing → 오늘
    /briefing/2026-05-04 → 특정 날짜 아카이브
    """
    import re as _re_date
    if date_str and not _re_date.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return "Invalid date", 400

    briefing = daily_briefing.get_or_generate(date_str)
    archives = daily_briefing.list_archives(limit=14)

    if not briefing:
        # 과거 날짜인데 데이터 없음
        from flask import abort
        abort(404)

    return render_template("briefing.html", briefing=briefing, archives=archives)


@app.route("/api/briefing/summary")
def briefing_summary():
    """모달 팝업용 경량 요약 — 지수·환율·공포탐욕·뉴스 3건만."""
    try:
        briefing = daily_briefing.get_or_generate()
    except Exception:
        app.logger.exception("briefing summary failed")
        return jsonify({"available": False}), 200

    if not briefing:
        return jsonify({"available": False}), 200

    return jsonify({
        "available": True,
        "date": briefing.get("date"),
        "weekday_kr": briefing.get("weekday_kr"),
        "us_indices": briefing.get("us_indices"),
        "kr_indices": briefing.get("kr_indices"),
        "fx": briefing.get("fx"),
        "fear_greed": briefing.get("fear_greed"),
        "top_news_kr": (briefing.get("news_kr") or [])[:3],
        "top_news_us": (briefing.get("news_us") or [])[:3],
    })


@app.route("/cron/daily-briefing", methods=["POST", "GET"])
def cron_briefing():
    """외부 cron이 호출 — 매일 오전 9:30 KST에 브리핑 자동 생성.

    인증: X-Cron-Token 헤더 또는 ?token= 쿼리스트링 필수.
    환경변수 CRON_TOKEN과 일치해야 실행.
    """
    expected = os.getenv("CRON_TOKEN")
    if not expected:
        return jsonify({"error": "CRON_TOKEN 환경변수 미설정"}), 503
    provided = request.headers.get("X-Cron-Token") or request.args.get("token") or ""
    # 상수 시간 비교 — 토큰 길이·내용 추측 timing attack 방어
    if not hmac.compare_digest(provided, expected):
        return jsonify({"error": "forbidden"}), 403

    try:
        briefing = daily_briefing.generate_briefing()
        path = daily_briefing.save_briefing(briefing)
        # 캐시도 갱신
        cache.set(f"daily_briefing:{briefing['date']}", briefing, ttl=3600)
        return jsonify({
            "ok": True,
            "date": briefing["date"],
            "saved_to": path,
            "summary": {
                "us_sp500": briefing.get("us_indices", {}).get("sp500"),
                "kr_kospi": briefing.get("kr_indices", {}).get("kospi"),
                "news_count": len(briefing.get("news_us", [])) + len(briefing.get("news_kr", [])),
            },
        })
    except Exception as e:
        app.logger.exception("briefing cron failed")
        return jsonify({"error": f"{type(e).__name__}: {str(e)[:200]}"}), 500


@app.route("/api/news", methods=["POST"])
def analyze_news():
    """종목 관련 뉴스 — 네이버 검색 API. 탭 클릭 시 lazy load.

    회사명을 query로 사용 (티커보다 매칭 잘됨). 한국 종목은 longName,
    미국 종목은 longName 또는 한국어 매핑 우선.
    제목·요약·링크만 반환 (저작권 안전 — 본문은 원본 사이트로).
    """
    body = request.get_json(force=True, silent=True) or {}
    raw_query = (body.get("ticker") or "").strip()
    if not raw_query:
        return jsonify({"available": False, "error": "티커 필요"}), 400
    if not is_safe_query(raw_query):
        return jsonify({"available": False, "error": "허용되지 않는 문자"}), 400
    if not naver_news.is_available():
        return jsonify({"available": False, "error": "뉴스 API 미설정 (NAVER_CLIENT_ID 환경변수 필요)"}), 200

    ticker = resolve_ticker(raw_query) or raw_query.upper()
    is_kr = ticker.endswith(".KS") or ticker.endswith(".KQ")

    # 검색어 결정 — 회사명 우선, 없으면 티커
    search_query = ""
    if is_kr:
        # 한국: KR_STOCKS reverse lookup ("005930.KS" → "삼성전자")
        for name, (tk, _eng) in KR_STOCKS.items():
            if tk == ticker:
                search_query = name
                break
        if not search_query:
            # KRX listing fallback
            try:
                code = ticker.split(".")[0]
                listings = kr_listing.get_listings() if hasattr(kr_listing, "get_listings") else []
                for item in (listings or []):
                    if item.get("code") == code:
                        search_query = item.get("name") or ""
                        break
            except Exception:
                pass
    else:
        # 미국: US_STOCKS_KR reverse lookup ("AAPL" → "애플"), 없으면 티커
        for kr_name, tk in US_STOCKS_KR.items():
            if tk == ticker:
                search_query = kr_name
                break

    if not search_query:
        search_query = ticker

    items = naver_news.fetch_news(search_query, display=8, sort="date")
    if items is None:
        return jsonify({"available": False, "error": "뉴스 일시 불가"}), 200

    return jsonify({
        "available": True,
        "query": search_query,
        "ticker": ticker,
        "items": items,
        "source": "네이버 검색 API",
    })


@app.route("/api/krx", methods=["POST"])
def analyze_krx():
    """한국 종목 수급 정보 — 외국인·기관·공매도. 탭 클릭 시 lazy load."""
    import concurrent.futures
    body = request.get_json(force=True, silent=True) or {}
    raw_query = (body.get("ticker") or "").strip()
    if not raw_query:
        return jsonify({"available": False, "error": "티커 필요"}), 400
    if not is_safe_query(raw_query):
        return jsonify({"available": False, "error": "허용되지 않는 문자"}), 400
    ticker = resolve_ticker(raw_query) or raw_query.upper()
    if not (ticker.endswith(".KS") or ticker.endswith(".KQ")):
        return jsonify({"available": False, "error": "한국 종목만 지원"}), 400
    if not krx_client.is_available():
        return jsonify({"available": False, "error": "KRX 클라이언트 미설치"}), 503

    # 외부 호출 timeout 방어 — 8초 안에 못 받으면 None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(krx_client.fetch_all, ticker)
            result = future.result(timeout=8.0)
            return jsonify(result)
    except concurrent.futures.TimeoutError:
        app.logger.warning(f"KRX timeout for {ticker}")
        return jsonify({"available": False, "error": "KRX 응답 지연 — 잠시 후 다시 시도"}), 200
    except Exception:
        app.logger.exception("krx fail")
        return jsonify({"available": False, "error": "KRX 데이터 일시 불가"}), 200


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
    if not is_safe_query(raw_query):
        return jsonify({"available": False, "error": "허용되지 않는 문자"}), 400
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


def _debug_enabled() -> bool:
    """디버그 엔드포인트는 STOCKINTO_DEBUG=1 + 로컬/사설 IP에서만 활성.

    운영서버에서 누군가 실수로 STOCKINTO_DEBUG=1을 켜도 외부 IP는 접근 불가
    (DART 키 prefix·env 길이 leak 방지).
    """
    if os.getenv("STOCKINTO_DEBUG", "0") != "1":
        return False
    return _is_local_or_private_ip()


@app.route("/api/debug/echo", methods=["POST"])
def debug_echo():
    """body가 어떻게 들어오는지 확인 (STOCKINTO_DEBUG=1 일 때만)."""
    if not _debug_enabled():
        return jsonify({"error": "Not Found"}), 404
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
    """DART 연결 진단 (STOCKINTO_DEBUG=1 일 때만)."""
    if not _debug_enabled():
        return jsonify({"error": "Not Found"}), 404
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
    # 기본은 localhost — LAN 무방비 노출 방지. 외부 노출 필요시 HOST=0.0.0.0 명시
    host = os.getenv("HOST", "127.0.0.1")
    app.run(debug=debug, host=host, port=port)
