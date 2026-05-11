"""정적 페이지 라우트 — render_template + 정적 파일 서빙.

라우트:
- 한국어: /, /stock/<ticker>, /install, /glossary, /terms, /privacy, /contact, /about
         /learn/<topic>, /picks/<topic>, /briefing, /briefing/<date_str>
- 영어:  /en/, /en, /en/about, /en/learn/<topic>, /en/picks/<topic>
- 정적:  /sw.js, /ads.txt, /robots.txt, /favicon.ico, /sitemap.xml
"""
import re

from flask import Blueprint, Response, abort, redirect, render_template, send_from_directory

from data import daily_briefing
from kr_stocks import KR_STOCKS


pages_bp = Blueprint("pages", __name__)


# ============================================================
# 메인 + 정적 파일
# ============================================================
@pages_bp.route("/")
def index():
    return render_template("index.html")


@pages_bp.route("/sw.js")
def sw_js_root():
    # Service Worker는 스코프 문제로 루트에서 서빙
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@pages_bp.route("/ads.txt")
def ads_txt():
    """Google AdSense ads.txt — 광고 사기 방지 표준."""
    return send_from_directory("static", "ads.txt", mimetype="text/plain")


@pages_bp.route("/robots.txt")
def robots_txt():
    return send_from_directory("static", "robots.txt", mimetype="text/plain")


@pages_bp.route("/favicon.ico")
def favicon():
    """루트 favicon — 구글·네이버 검색 결과용. 정적 캐시 1년."""
    resp = send_from_directory("static", "favicon.ico", mimetype="image/x-icon")
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


@pages_bp.route("/sitemap.xml")
def sitemap_xml():
    """정적 페이지 + 인기 종목 100여개 동적 sitemap 생성."""
    static_pages = [
        ("/", "daily", "1.0"),
        ("/about", "monthly", "0.9"),
        ("/glossary", "weekly", "0.8"),
        ("/briefing", "daily", "0.9"),
        ("/screener", "weekly", "0.9"),
        ("/learn/buffett-criteria", "monthly", "0.85"),
        ("/learn/dcf-guide", "monthly", "0.85"),
        ("/learn/graham-criteria", "monthly", "0.85"),
        ("/learn/lynch-criteria", "monthly", "0.85"),
        ("/learn/oneil-criteria", "monthly", "0.85"),
        ("/learn/fisher-criteria", "monthly", "0.85"),
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
    return Response("\n".join(parts), mimetype="application/xml")


# ============================================================
# 종목별 SEO 페이지 (한국어)
# ============================================================
@pages_bp.route("/stock/<ticker>")
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


# ============================================================
# 한국어 정적 페이지
# ============================================================
@pages_bp.route("/screener")
def screener():
    """주식 스크리너 — 조건 필터로 종목 발굴."""
    return render_template("screener.html")


@pages_bp.route("/install")
def install_guide():
    return render_template("install.html")


@pages_bp.route("/glossary")
def glossary():
    return render_template("glossary.html")


@pages_bp.route("/terms")
def terms():
    return render_template("terms.html")


@pages_bp.route("/privacy")
def privacy():
    return render_template("privacy.html")


@pages_bp.route("/contact")
def contact():
    return render_template("contact.html")


@pages_bp.route("/about")
def about():
    return render_template("about.html")


# ===== 학습 가이드 (장문 SEO 콘텐츠) =====
LEARN_TEMPLATES = {
    "buffett-criteria": "learn_buffett.html",
    "dcf-guide": "learn_dcf.html",
    "graham-criteria": "learn_graham.html",
    "lynch-criteria": "learn_lynch.html",
    "oneil-criteria": "learn_oneil.html",
    "fisher-criteria": "learn_fisher.html",
}


@pages_bp.route("/learn/<topic>")
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


@pages_bp.route("/picks/<topic>")
def picks_topic(topic: str):
    """종목 큐레이션 페이지 — 내부 링크 강화 + SEO."""
    tpl = PICKS_TEMPLATES.get(topic)
    if not tpl:
        return redirect("/", code=302)
    return render_template(tpl)


# ============================================================
# 영어 라우트 (i18n Phase 1)
# ============================================================
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


@pages_bp.route("/en/")
@pages_bp.route("/en")
def en_index():
    return render_template("en/index.html")


@pages_bp.route("/en/about")
def en_about():
    return render_template("en/about.html")


@pages_bp.route("/en/learn/<topic>")
def en_learn(topic: str):
    tpl = EN_LEARN_TEMPLATES.get(topic)
    if not tpl:
        return redirect("/en/", code=302)
    return render_template(tpl)


@pages_bp.route("/en/picks/<topic>")
def en_picks(topic: str):
    tpl = EN_PICKS_TEMPLATES.get(topic)
    if not tpl:
        return redirect("/en/", code=302)
    return render_template(tpl)


# ============================================================
# 일일 브리핑 페이지 (전체 보기)
# ============================================================
@pages_bp.route("/briefing")
@pages_bp.route("/briefing/<date_str>")
def briefing_page(date_str=None):
    """일일 금융 브리핑 페이지 — 매일 자동 갱신.

    /briefing → 오늘
    /briefing/2026-05-04 → 특정 날짜 아카이브
    """
    if date_str and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return "Invalid date", 400

    briefing = daily_briefing.get_or_generate(date_str)
    archives = daily_briefing.list_archives(limit=14)

    if not briefing:
        # 과거 날짜인데 데이터 없음
        abort(404)

    return render_template("briefing.html", briefing=briefing, archives=archives)
