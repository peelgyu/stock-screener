/**
 * StockInto i18n — 클라이언트 사이드 다국어 지원
 *
 * 사용법:
 *  1) HTML: <span data-i18n="key.name">기본 한국어 텍스트</span>
 *           <input data-i18n-placeholder="key.placeholder">
 *           <a data-i18n-aria-label="key.aria">
 *  2) JS:   element.innerHTML = t('key.name');
 *           element.innerHTML = t('key.with_var', {ticker: 'AAPL'});
 *  3) 토글: <button onclick="setLang('en')">EN</button>
 *
 * 새 기능 추가 시:
 *  - I18N_DICT.ko에 키·한국어 추가
 *  - I18N_DICT.en에 키·영어 추가 (누락 시 한국어 fallback + console.warn)
 *  - HTML 정적 텍스트는 data-i18n 속성 사용
 *  - JS 동적 텍스트는 t('key') 호출
 */

(function (global) {
    'use strict';

    // ===== 사전 (한국어 = source of truth, 영어 = 번역) =====
    const I18N_DICT = {
        ko: {
            // ===== 공통 nav =====
            'nav.home': '🏠 메인',
            'nav.about': 'ℹ 소개',
            'nav.glossary': '📚 용어',
            'nav.install': '📱 앱',
            'nav.contact': '✉ 문의',
            'nav.briefing': '📊 일일 브리핑',
            'nav.terms': '이용약관',
            'nav.privacy': '개인정보처리방침',
            'nav.lang_to_en': '🇺🇸 EN',
            'nav.lang_to_ko': '🇰🇷 한국어',
            'nav.lang_to_en_aria': 'View in English',
            'nav.lang_to_ko_aria': '한국어로 보기',

            // ===== 메인 hero =====
            'hero.catch_html': '<span class="accent">워렌 버핏</span>이라면,<br>이 주식을 살까?',
            'hero.sub': '스톡인투(StockInto) — 워렌 버핏부터 피터 린치까지 · 5명의 전설이 채점합니다',
            'search.placeholder': '종목명 또는 티커 (예: 애플, 삼성전자, NVDA)',
            'search.button': '분석',
            'search.aria': '종목 분석 시작',
            'search.hint': '종목명 또는 티커를 입력하고 분석 버튼을 누르거나 엔터를 치세요. 자동완성 목록이 나타나면 화살표 키로 선택할 수 있습니다.',

            // ===== 빠른 검색 =====
            'quick.popular': '🔥 지금 많이 찾는 종목',
            'quick.favorites': '⭐ 내 관심 종목',
            'quick.favorites_hint': '— 클릭해서 분석',
            'quick.history': '🕓 최근 본 종목',
            'quick.clear': '초기화',
            'quick.clear_aria': '최근 본 종목 초기화',

            // ===== 프로모 카드 =====
            'promo.install_title': '앱처럼 바로 쓰기',
            'promo.install_sub': '홈 화면 아이콘으로 즉시 실행. 30초면 끝.',
            'promo.install_cta': '설치 방법 보기 →',
            'promo.glossary_title': '주식 용어 한눈에',
            'promo.glossary_sub': 'PER, ROE, DCF, RSI... 70+ 용어 검색.',
            'promo.glossary_cta': '용어 사전 →',

            // ===== 분석 결과 — 5인 거장 =====
            'inv.buffett': '워렌 버핏',
            'inv.graham': '벤저민 그레이엄',
            'inv.lynch': '피터 린치',
            'inv.oneil': '윌리엄 오닐',
            'inv.fisher': '필립 피셔',
            'inv.buffett_q': '워렌 버핏이라면?',
            'inv.graham_q': '그레이엄이라면?',
            'inv.lynch_q': '린치라면?',
            'inv.oneil_q': '오닐이라면?',
            'inv.fisher_q': '피셔라면?',

            // ===== 등급 라벨 =====
            'grade.suffix_meets': '기준 충족',
            'grade.suffix_partial': '기준 부분 충족',
            'grade.suffix_short': '기준 미달',
            'grade.suffix_fail': '기준 대부분 미충족',
            'grade.passed': '통과',
            'grade.failed': '미통과',
            'grade.no_data': '데이터 없음',

            // ===== 탭 =====
            'tab.investors': '🧠 워렌 버핏이라면?',
            'tab.trend': '📆 재무 추세',
            'tab.krx': '🇰🇷 수급',
            'tab.news': '📰 관련 뉴스',
            'tab.sentiment': '😱 탐욕지수',
            'tab.positions': '📊 숏/롱',
            'tab.options': '🎯 옵션',

            // ===== 분석 결과 일반 =====
            'analysis.loading': '데이터 분석 중...',
            'analysis.error_generic': '분석 중 오류가 발생했습니다.',
            'analysis.error_not_found': '종목을 찾을 수 없습니다.',
            'analysis.fair_value': '적정주가',
            'analysis.current_price': '현재가',
            'analysis.upside': '상승여력',
            'analysis.downside': '하락여력',
            'analysis.margin_safety': '안전마진',
            'analysis.sector': '섹터',
            'analysis.market_cap': '시가총액',
            'analysis.see_data': '근거 데이터 보기',

            // ===== 영어 사용자 배너 =====
            'banner.en_user': '🇺🇸 English visitor?',
            'banner.en_user_desc': 'Stock analysis is currently in Korean only — but the data (PER, ROE, fair value, charts) is universal.',
            'banner.en_user_back': '← Back to English site',

            // ===== 면책 =====
            'disclaimer.title': '⚠ 본 서비스는 투자 참고용이며, 투자 권유·조언·자문이 아닙니다.',
            'disclaimer.body': '본 서비스는 자본시장법상 투자자문업·유사투자자문업이 아니며, 인가된 금융투자업자가 아닙니다. 제공되는 모든 분석·등급·점수는 공개 데이터 기반 참고 정보이며, 투자 판단과 그에 따른 결과의 책임은 이용자 본인에게 있습니다.',

            // ===== 일일 브리핑 =====
            'briefing.title': '📊 전날 시황 브리핑',
            'briefing.us_indices': '🇺🇸 미국 지수',
            'briefing.kr_indices': '🇰🇷 한국 지수',
            'briefing.fx': '💱 환율',
            'briefing.fear_greed': '😱 공포·탐욕 지수',
            'briefing.top_gainers': '📈 상승 TOP',
            'briefing.top_losers': '📉 하락 TOP',
            'briefing.news_us': '📰 미국 시장 뉴스',
            'briefing.news_kr': '📰 한국 시장 뉴스',
            'briefing.modal_full': '📄 전체 보기',
            'briefing.modal_dismiss_today': '오늘 그만 보기',
            'briefing.modal_never': '다시는 보지 않기',

            // ===== FAQ =====
            'faq.heading': '자주 묻는 질문 (FAQ)',
            'faq.q1': 'PER 몇이면 비싼 건가요?',
            'faq.q2': 'A 등급 종목은 무조건 사도 되나요?',
            'faq.q3': 'DCF 적정가는 어떻게 계산하나요?',
            'faq.q4': '한국 종목은 어디서 데이터를 가져오나요?',
            'faq.q5': '버핏의 9가지 기준은 정확히 무엇인가요?',
            'faq.q6': '유료인가요? 회원가입 필요한가요?',
            'faq.q7': '분석 결과로 손해가 나면 책임지나요?',
            'faq.q8': '앱으로 설치할 수 있나요?',

            // ===== SEO 섹션 =====
            'seo.why_heading': '왜 5인 거장 기준으로 분석하나요?',
            'seo.guide_heading': '이렇게 활용하세요 — 3단계 가이드',
            'seo.popular_heading': '🔥 지금 인기 분석 종목',
            'seo.popular_hint': '티커를 클릭하면 바로 분석 결과로 이동합니다.',
            'seo.step1_tag': 'STEP 1 · 검색',
            'seo.step1_title': '종목명·티커 입력',
            'seo.step2_tag': 'STEP 2 · 분석',
            'seo.step2_title': '5인 채점 + 적정주가',
            'seo.step3_tag': 'STEP 3 · 결정',
            'seo.step3_title': '근거 보고 직접 판단',
            'seo.cta_buffett': '🎯 버핏 스타일 종목 모음 →',
            'seo.cta_dividend': '💰 배당 귀족주 모음 →',
            'seo.learn_more': '더 깊이 알아보기 →',
        },
        en: {
            'nav.home': '🏠 Home',
            'nav.about': 'ℹ About',
            'nav.glossary': '📚 Glossary',
            'nav.install': '📱 Install',
            'nav.contact': '✉ Contact',
            'nav.briefing': '📊 Daily Briefing',
            'nav.terms': 'Terms',
            'nav.privacy': 'Privacy',
            'nav.lang_to_en': '🇺🇸 EN',
            'nav.lang_to_ko': '🇰🇷 KO',
            'nav.lang_to_en_aria': 'View in English',
            'nav.lang_to_ko_aria': 'View in Korean',

            'hero.catch_html': 'What would <span class="accent">Warren Buffett</span><br>buy today?',
            'hero.sub': 'StockInto — 5 legendary investors score every stock. Buffett, Graham, Lynch, O\'Neil, Fisher.',
            'search.placeholder': 'Ticker or name (e.g. AAPL, MSFT, NVDA, 005930.KS)',
            'search.button': 'Analyze',
            'search.aria': 'Start stock analysis',
            'search.hint': 'Type a ticker or company name and press Analyze or Enter. Use arrow keys to navigate the autocomplete list.',

            'quick.popular': '🔥 Trending stocks',
            'quick.favorites': '⭐ My watchlist',
            'quick.favorites_hint': '— click to analyze',
            'quick.history': '🕓 Recently viewed',
            'quick.clear': 'Clear',
            'quick.clear_aria': 'Clear recent stocks',

            'promo.install_title': 'Use as an app',
            'promo.install_sub': 'Add to home screen — 30 seconds, no download.',
            'promo.install_cta': 'Install guide →',
            'promo.glossary_title': 'Investing glossary',
            'promo.glossary_sub': 'PER, ROE, DCF, RSI... 70+ terms searchable.',
            'promo.glossary_cta': 'Open glossary →',

            'inv.buffett': 'Warren Buffett',
            'inv.graham': 'Benjamin Graham',
            'inv.lynch': 'Peter Lynch',
            'inv.oneil': 'William O\'Neil',
            'inv.fisher': 'Philip Fisher',
            'inv.buffett_q': 'What would Warren Buffett do?',
            'inv.graham_q': 'What would Graham do?',
            'inv.lynch_q': 'What would Lynch do?',
            'inv.oneil_q': 'What would O\'Neil do?',
            'inv.fisher_q': 'What would Fisher do?',

            'grade.suffix_meets': 'criteria met',
            'grade.suffix_partial': 'criteria partially met',
            'grade.suffix_short': 'criteria mostly unmet',
            'grade.suffix_fail': 'criteria mostly failed',
            'grade.passed': 'PASS',
            'grade.failed': 'FAIL',
            'grade.no_data': 'no data',

            'tab.investors': '🧠 What would Buffett do?',
            'tab.trend': '📆 Financial Trends',
            'tab.krx': '🇰🇷 KRX Flow',
            'tab.news': '📰 Related News',
            'tab.sentiment': '😱 Fear & Greed',
            'tab.positions': '📊 Short/Long',
            'tab.options': '🎯 Options',

            'analysis.loading': 'Analyzing...',
            'analysis.error_generic': 'An error occurred during analysis.',
            'analysis.error_not_found': 'Stock not found.',
            'analysis.fair_value': 'Fair Value',
            'analysis.current_price': 'Current Price',
            'analysis.upside': 'Upside',
            'analysis.downside': 'Downside',
            'analysis.margin_safety': 'Margin of Safety',
            'analysis.sector': 'Sector',
            'analysis.market_cap': 'Market Cap',
            'analysis.see_data': 'View underlying data',

            'banner.en_user': '🇺🇸 English visitor?',
            'banner.en_user_desc': 'Stock analysis is currently in Korean only — but the data (PER, ROE, fair value, charts) is universal.',
            'banner.en_user_back': '← Back to English site',

            'disclaimer.title': '⚠ This service is for reference only — not investment advice.',
            'disclaimer.body': 'StockInto is not a registered investment advisor under Korean Capital Markets Act, nor a licensed financial services provider. All analyses, grades, and scores are reference information from public data. Investment decisions and outcomes are solely your responsibility.',

            'briefing.title': '📊 Daily Market Briefing',
            'briefing.us_indices': '🇺🇸 US Indices',
            'briefing.kr_indices': '🇰🇷 Korean Indices',
            'briefing.fx': '💱 FX Rate',
            'briefing.fear_greed': '😱 Fear & Greed Index',
            'briefing.top_gainers': '📈 Top Gainers',
            'briefing.top_losers': '📉 Top Losers',
            'briefing.news_us': '📰 US Market News',
            'briefing.news_kr': '📰 Korean Market News',
            'briefing.modal_full': '📄 View full briefing',
            'briefing.modal_dismiss_today': 'Hide for today',
            'briefing.modal_never': 'Don\'t show again',

            'faq.heading': 'Frequently Asked Questions',
            'faq.q1': 'What PER is considered expensive?',
            'faq.q2': 'Should I always buy A-grade stocks?',
            'faq.q3': 'How is DCF fair value calculated?',
            'faq.q4': 'Where does Korean stock data come from?',
            'faq.q5': 'What exactly are Buffett\'s 9 criteria?',
            'faq.q6': 'Is it free? Do I need to register?',
            'faq.q7': 'Are you responsible if I lose money?',
            'faq.q8': 'Can I install it as an app?',

            'seo.why_heading': 'Why score stocks against 5 legendary investors?',
            'seo.guide_heading': 'How to use it — 3-step guide',
            'seo.popular_heading': '🔥 Popular stocks to analyze',
            'seo.popular_hint': 'Click any ticker for instant analysis.',
            'seo.step1_tag': 'STEP 1 · SEARCH',
            'seo.step1_title': 'Enter ticker or name',
            'seo.step2_tag': 'STEP 2 · ANALYZE',
            'seo.step2_title': '5-investor scoring + fair value',
            'seo.step3_tag': 'STEP 3 · DECIDE',
            'seo.step3_title': 'Read the evidence, decide yourself',
            'seo.cta_buffett': '🎯 Buffett-style picks →',
            'seo.cta_dividend': '💰 Dividend Aristocrats →',
            'seo.learn_more': 'Learn more →',
        },
    };

    // ===== 현재 언어 =====
    function getLang() {
        try {
            const v = localStorage.getItem('lang_pref');
            return v === 'en' ? 'en' : 'ko';
        } catch (e) {
            return 'ko';
        }
    }

    // ===== 번역 헬퍼 =====
    // t('key.name') → 현재 언어 번역
    // t('key.name', {ticker: 'AAPL'}) → {ticker} 변수 치환
    // 키 누락 시: 영어 모드라면 한국어 fallback + console.warn, 한국어 모드는 키 그대로
    function t(key, vars) {
        const lang = getLang();
        const dict = I18N_DICT[lang] || I18N_DICT.ko;
        let value = dict[key];
        if (value === undefined) {
            if (lang === 'en' && I18N_DICT.ko[key] !== undefined) {
                console.warn('[i18n] missing en translation for:', key);
                value = I18N_DICT.ko[key];
            } else {
                console.warn('[i18n] missing key:', key);
                return key;
            }
        }
        if (vars && typeof vars === 'object') {
            for (const k in vars) {
                value = value.split('{' + k + '}').join(vars[k]);
            }
        }
        return value;
    }

    // ===== DOM 자동 교체 =====
    // <span data-i18n="key">기본 텍스트</span>     → innerHTML 교체
    // <input data-i18n-placeholder="key">         → placeholder 속성 교체
    // <button data-i18n-aria-label="key">         → aria-label 속성 교체
    // <input data-i18n-value="key">               → value 속성 교체 (버튼 등)
    function applyI18n(root) {
        const r = root || document;
        r.querySelectorAll('[data-i18n]').forEach(function (el) {
            const key = el.getAttribute('data-i18n');
            el.innerHTML = t(key);
        });
        r.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
            el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder')));
        });
        r.querySelectorAll('[data-i18n-aria-label]').forEach(function (el) {
            el.setAttribute('aria-label', t(el.getAttribute('data-i18n-aria-label')));
        });
        r.querySelectorAll('[data-i18n-value]').forEach(function (el) {
            el.setAttribute('value', t(el.getAttribute('data-i18n-value')));
        });
        r.querySelectorAll('[data-i18n-title]').forEach(function (el) {
            el.setAttribute('title', t(el.getAttribute('data-i18n-title')));
        });
        // <html lang> 속성 갱신 (접근성·SEO)
        const lang = getLang();
        document.documentElement.setAttribute('lang', lang === 'en' ? 'en' : 'ko');
        // 언어 토글 버튼 (#langToggle) — 현재 언어의 반대를 표시
        const toggle = r.querySelector ? r.querySelector('#langToggle') : null;
        if (toggle) {
            toggle.innerHTML = lang === 'en' ? t('nav.lang_to_ko') : t('nav.lang_to_en');
            toggle.setAttribute('aria-label', lang === 'en' ? t('nav.lang_to_ko_aria') : t('nav.lang_to_en_aria'));
        }
        // 언어별 큰 블록 토글 — 긴 본문은 키 매핑보다 div 두 벌이 효율적
        // <div class="lang-ko">한국어 본문</div>
        // <div class="lang-en">English content</div>
        r.querySelectorAll('.lang-ko').forEach(function (el) {
            el.style.display = lang === 'en' ? 'none' : '';
        });
        r.querySelectorAll('.lang-en').forEach(function (el) {
            el.style.display = lang === 'en' ? '' : 'none';
        });
    }

    // ===== 언어 전환 =====
    function setLang(lang) {
        const next = lang === 'en' ? 'en' : 'ko';
        try { localStorage.setItem('lang_pref', next); } catch (e) {}
        // 페이지 reload — 모든 텍스트 즉시 교체 (SSR된 정적 HTML도 포함)
        window.location.reload();
    }

    // ===== DOMContentLoaded 시 자동 적용 =====
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { applyI18n(); });
    } else {
        applyI18n();
    }

    // ===== 전역 노출 =====
    global.t = t;
    global.applyI18n = applyI18n;
    global.setLang = setLang;
    global.getLang = getLang;
    global.I18N_DICT = I18N_DICT;
})(window);
