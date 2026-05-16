"""유명 투자자 기준 주식 스크리너 - Flask 웹앱 (개선판)."""

import os
import math
import time
import logging
import ipaddress
import urllib.request
import urllib.parse
import json as json_lib
from collections import defaultdict

_init_logger = logging.getLogger(__name__)

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
    except Exception as e:
        # Sentry init 실패는 silent로 두면 에러 추적 OFF인 채로 운영됨 → 반드시 로깅
        _init_logger.warning("Sentry SDK init failed (error tracking disabled): %s", e)

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
from analysis.oneil import evaluate_oneil
from analysis.fear_greed import evaluate_fear_greed
from analysis.options import evaluate_options
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

# Blueprint 등록 — 라우트 분리 (routes/ 폴더)
# 모든 라우트가 routes/ 하위 5개 Blueprint로 분리 완료
from routes import cron_bp, debug_bp, api_market_bp, pages_bp, api_stock_bp
app.register_blueprint(cron_bp)
app.register_blueprint(debug_bp)
app.register_blueprint(api_market_bp)
app.register_blueprint(pages_bp)
app.register_blueprint(api_stock_bp)

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
_ALLOWED_ORIGINS = {
    "https://stockinto.com",
    "https://www.stockinto.com",
    "https://stockinto.co.kr",
    "https://www.stockinto.co.kr",
}
# 환경변수 ALLOWED_ORIGINS_EXTRA로 추가 origin도 콤마구분 등록 가능
_extra = (os.getenv("ALLOWED_ORIGINS_EXTRA") or "").strip()
if _extra:
    for o in _extra.split(","):
        o = o.strip().rstrip("/")
        if o:
            _ALLOWED_ORIGINS.add(o)


def _is_origin_allowed(origin: str) -> bool:
    """Origin 허용 여부 — 화이트리스트 매칭."""
    if not origin:
        return False
    o = origin.rstrip("/")
    return o in _ALLOWED_ORIGINS


@app.before_request
def _csrf_origin_check():
    """POST API 요청은 Origin/Referer가 자기 도메인이어야 함 (CSRF 차단)."""
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
    CSP 4차(2026-05-16): templates 인라인 style 0건 달성 → 'style-src unsafe-inline' 제거,
    JS API 통해 설정되는 element.style은 'style-src-attr unsafe-inline'로 별도 보호.
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
        "style-src 'self' https://cdn.jsdelivr.net; "
        "style-src-attr 'unsafe-inline'; "
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
# 공유 헬퍼는 utils.py로 이동 — is_safe_query, resolve_ticker, get_stock_data
from utils import is_safe_query, resolve_ticker, get_stock_data


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    port = int(os.getenv("PORT", "5000"))
    # 기본은 localhost — LAN 무방비 노출 방지. 외부 노출 필요시 HOST=0.0.0.0 명시
    host = os.getenv("HOST", "127.0.0.1")
    app.run(debug=debug, host=host, port=port)
