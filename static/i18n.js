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
            'nav.market': '📊 시황',
            'nav.investors_menu': '🧠 유명 투자자',
            'nav.picks': '🎯 큐레이션',
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

            // ===== 분석 결과 — 유명 투자자 5명 =====
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
            'seo.why_heading': '왜 유명 투자자 5명의 기준으로 분석하나요?',
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
            'nav.market': '📊 Market',
            'nav.investors_menu': '🧠 Legendary Investors',
            'nav.picks': '🎯 Picks',
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

    // ===== 백엔드 응답 한국어 → 영어 매핑 사전 =====
    // 백엔드(Python 분석 모듈)에서 보내는 한국어 라벨을 영어 모드에서 자동 교체.
    // 정확 매칭이 우선이고, 변수 포함 텍스트는 BACKEND_PATTERNS로 처리.
    const BACKEND_TEXT_MAP = {
        // 등급·유명 투자자
        '워렌 버핏': 'Warren Buffett', '벤저민 그레이엄': 'Benjamin Graham',
        '피터 린치': 'Peter Lynch', '윌리엄 오닐': "William O'Neil", '필립 피셔': 'Philip Fisher',

        // 통과/미통과·일반 라벨
        '통과': 'PASS', '미통과': 'FAIL', '데이터 없음': 'no data', '데이터 부족': 'insufficient data',
        '특이점 없음': 'no anomalies', '일반': 'general', '보통': 'normal', '중간': 'medium',
        '높은 변동성': 'high volatility', '조정': 'correction',
        '강세 우세': 'bullish', '약세 베팅 우세': 'bearish bias', '강한 약세 베팅': 'strong bearish bet',
        '소폭 약세': 'slightly bearish',
        '증가': 'increased', '감소': 'decreased',

        // 공포탐욕 라벨
        '공포': 'Fear', '탐욕': 'Greed', '중립': 'Neutral',
        '극단적 공포': 'Extreme Fear', '극단적 탐욕': 'Extreme Greed',
        '극단적 변동 (공포)': 'Extreme Volatility (Fear)', '안정적 (탐욕)': 'Stable (Greed)',
        '과매수 (탐욕)': 'Overbought (Greed)', '과매도 (공포)': 'Oversold (Fear)',
        '고점 근처 (탐욕)': 'Near 52-week High (Greed)', '저점 근처 (공포)': 'Near 52-week Low (Fear)',
        '이평선 위 (탐욕)': 'Above MA (Greed)', '이평선 아래 (공포)': 'Below MA (Fear)',
        '이평선 근처': 'Near MA',
        '장기 상승세 (탐욕)': 'Long-term Uptrend (Greed)', '장기 하락세 (공포)': 'Long-term Downtrend (Fear)',
        '매수세 증가': 'Buying Pressure Up', '매도세 증가': 'Selling Pressure Up',
        'RSI (14일)': 'RSI (14d)',
        '52주 범위 위치': '52-week Range Position',
        '50일 이평선 대비': 'vs 50-day MA',
        '200일 이평선 대비': 'vs 200-day MA',
        '거래량 변화 (5일/20일)': 'Volume Change (5d/20d)',
        '변동성 (연환산)': 'Volatility (annualized)',

        // 평가자 기준 라벨 (정확 매칭 가능한 것들)
        'ROE (섹터 기준)': 'ROE (sector benchmark)',
        'ROE 20%+ (버핏 최선호)': 'ROE 20%+ (Buffett favorite)',
        'ROE 꾸준함 (다년도 15%+)': 'ROE consistency (multi-year 15%+)',
        '부채비율 (섹터 기준)': 'Debt ratio (sector benchmark)',
        '부채비율 <= 80%': 'Debt-to-equity <= 80%',
        '영업이익률 (섹터 기준)': 'Operating margin (sector benchmark)',
        '매출총이익률 (섹터 기준)': 'Gross margin (sector benchmark)',
        '순이익률 (섹터 기준)': 'Net margin (sector benchmark)',
        '매출 성장 중': 'Revenue growing',
        '매출 성장률 > 10%': 'Revenue growth > 10%',
        'EPS 성장률 > 15%': 'EPS growth > 15%',
        'EPS CAGR >= 10% (5년 복리)': 'EPS CAGR >= 10% (5-year compound)',
        '매출 CAGR >= 3%': 'Revenue CAGR >= 3%',
        '매출 CAGR >= 3% (장기 인플레 이상)': 'Revenue CAGR >= 3% (above long-term inflation)',
        '매출 CAGR >= 7% (장기 성장)': 'Revenue CAGR >= 7% (long-term growth)',
        'FCF 양수': 'Positive FCF',
        'FCF > 순이익 (우량한 현금 창출)': 'FCF > net income (strong cash generation)',
        'FCF가 순이익 대비 양호 (70%+)': 'FCF healthy vs net income (70%+)',
        '안전마진 30%+ (저평가)': 'Margin of Safety 30%+ (undervalued)',
        '수익 안정성 (5년 연속 흑자)': 'Earnings stability (5 consecutive profitable years)',
        '배당 1%+ (인플레 헤지)': 'Dividend 1%+ (inflation hedge)',
        '유동비율 >= 200%': 'Current ratio >= 200%',
        'Gross Margin 안정': 'Gross Margin Stable',
        'Gross Margin 안정 (편차 ≤5%p)': 'Gross Margin Stable (std ≤5pp)',
        'R&D 투자': 'R&D Investment',
        'R&D 투자 (섹터 특성)': 'R&D Investment (sector-specific)',
        '기관 보유 < 60%': 'Institutional holding < 60%',
        '기관 보유 < 60% (아직 안 알려진 종목)': 'Institutional < 60% (under-the-radar)',

        // CAN SLIM
        'C: 분기 EPS 성장 >= 25%': 'C: Quarterly EPS growth >= 25%',
        'A: 연간 EPS 성장 >= 25%': 'A: Annual EPS growth >= 25%',
        'N: 52주 고가 근처(85%+)': 'N: Near 52-week high (85%+)',
        'S: 거래량 >= 1.5x 평균': 'S: Volume >= 1.5x average',
        'L: RS Rating >= 80 (선도주)': 'L: RS Rating >= 80 (leader)',
        'I: 기관 보유 >= 20%': 'I: Institutional holding >= 20%',
        'M: 시장 방향 = 상승장': 'M: Market direction = uptrend',
        '시장 조정 중': 'Market in correction',
        '하락장': 'Downtrend',
        '시장 하락장 — 일반적으로 신규 진입 부담 구간': 'Market downtrend — generally not a favorable entry zone',

        // Lynch 카테고리
        '경기 순환주 (Cyclical)': 'Cyclical',
        '고성장주 (Fast Grower)': 'Fast Grower',
        '우량 안정주 (Stalwart)': 'Stalwart',
        '저성장주 (Slow Grower)': 'Slow Grower',
        '회생주 (Turnaround)': 'Turnaround',
        '자산주 (Asset Play)': 'Asset Play',
        '분류 불가': 'Unclassified',
        '경기 사이클에 따라 매출·이익 큰 변동': 'Large revenue/earnings swings with business cycle',
        '매출·이익 모두 20%+ 성장 — 텐베거 후보': 'Revenue + earnings both 20%+ growth — ten-bagger candidate',
        '꾸준한 성장 + 큰 시가총액 — 30~50% 수익 노림': 'Steady growth + large cap — targeting 30-50% returns',
        '성숙기업 — 배당 위주, 자본 차익 기대 낮음': 'Mature company — dividend focus, low capital gains expectation',
        '고부채 + 급격한 이익 회복 — 위험·고수익': 'High debt + sharp earnings recovery — high risk, high reward',
        '장부가 미만 거래 — 숨은 자산가치 노림': 'Trading below book value — hidden asset value play',
        '데이터 부족으로 카테고리 판정 어려움': 'Insufficient data to classify',

        // 등급
        'A 등급 (기준 통과율 매우 높음)': 'Grade A (very high pass rate)',
        'B 등급 (기준 통과율 높음)': 'Grade B (high pass rate)',
        'C 등급 (기준 통과율 보통)': 'Grade C (moderate pass rate)',
        'D 등급 (기준 통과율 낮음)': 'Grade D (low pass rate)',
        'F 등급 (기준 통과율 매우 낮음)': 'Grade F (very low pass rate)',

        // 적정가 verdict
        '적정가 대비 큰 상승여력 (+20% 이상)': 'Significant upside vs fair value (+20%+)',
        '적정가 대비 상승여력 (+10~20%)': 'Upside vs fair value (+10-20%)',
        '현재가가 적정가 근처 (±10%)': 'Current price near fair value (±10%)',
        '적정가 대비 프리미엄 반영 (10~20%)': 'Premium to fair value (10-20%)',
        '적정가 대비 큰 프리미엄 (20% 이상)': 'Significant premium to fair value (20%+)',
        '⚠ 신뢰도 낮음 — ': '⚠ Low confidence — ',

        // 어닝 퀄리티
        '재무품질 양호': 'Financial quality healthy',
        '재무품질 우려': 'Financial quality concerns',
        '발생액 비율 낮음 (회계 보수적)': 'Low accruals ratio (conservative accounting)',
        '매출채권 회전 개선 (현금회수 빨라짐)': 'Receivables turnover improving (faster cash collection)',
        '재고 회전 개선': 'Inventory turnover improving',
        '순이익 적자 — 품질 지표 의미 제한적': 'Net loss — quality metrics limited',
        '자본잠식': 'capital impairment',

        // 공매도·기관
        '공매도 수량': 'Short interest volume',
        '공매도 비율 (유통주식 대비)': 'Short % of float',
        '숏 커버 일수 (Days to Cover)': 'Days to Cover',
        '전월 대비 공매도 변화': 'Short change vs prior month',
        '기관 보유 비율': 'Institutional holding %',
        '내부자 보유 비율': 'Insider holding %',
        '유통 주식수': 'Float',
        '총 발행 주식수': 'Shares Outstanding',
        '강한 약세 베팅': 'Strong bearish bet',
        '공매도 비율이 매우 높아 숏스퀴즈 가능성 있음': 'Short ratio very high — possible short squeeze',
        '공매도가 상당히 잡혀있어 하락 압력 존재': 'Significant short positions — downward pressure',
        '공매도가 적어 시장이 낙관적': 'Low short interest — market optimistic',
        '적당한 수준의 공매도': 'Moderate short interest',
        '(높음)': '(high)', '(낮음)': '(low)', '(보통)': '(moderate)',
        '(매우 높음 - 숏스퀴즈 주의)': '(very high — short squeeze risk)',
        '(숏커버 어려움)': '(hard to cover)',

        // 옵션
        '강세 우세 (상승 베팅 > 하락 베팅)': 'Bullish (call > put bets)',
        '약세 우세 (하락 베팅 > 상승 베팅)': 'Bearish (put > call bets)',
        '극단적 강세 (상승 베팅 압도적)': 'Extreme bullish (calls dominate)',
        '극단적 약세 (하락 베팅 압도적)': 'Extreme bearish (puts dominate)',
        '현재가 근처 - 큰 변동 없을 가능성': 'Near current price — likely small move',
        '현재가 수준 - 상승 출발점': 'Current price level — upside starting point',
        '현재가 수준 - 하락 방어선': 'Current price level — downside support',
    };

    // 정규식 패턴 매칭 (변수 포함 텍스트)
    const BACKEND_PATTERNS = [
        // "버핏 기준 6/9 충족"
        [/^버핏 기준 (\d+\/\d+) 충족$/, "Buffett: $1 criteria met"],
        [/^버핏 기준 (\d+\/\d+) 충족 \(90%\+\)$/, "Buffett: $1 criteria met (90%+)"],
        [/^버핏 기준 (\d+\/\d+) 부분 충족$/, "Buffett: $1 criteria partially met"],
        [/^버핏 기준 (\d+\/\d+) 충족 — 미달 항목 다수$/, "Buffett: $1 criteria met — many failed"],
        [/^버핏 기준 (\d+\/\d+) 충족 — 대부분 미충족$/, "Buffett: $1 criteria met — mostly failed"],
        // "투자자 기준 통과율 80% (16/20)"
        [/^투자자 기준 통과율 (\d+)% \((\d+\/\d+)\)$/, "Investor pass rate $1% ($2)"],
        [/^투자자 기준 통과율 낮음 \((\d+)%\)$/, "Low investor pass rate ($1%)"],
        // "RS Rating 85 (선도주)"
        [/^RS Rating (\d+) \(선도주\)$/, "RS Rating $1 (leader)"],
        [/^RS Rating (\d+) \(시장 상회\)$/, "RS Rating $1 (above market)"],
        [/^RS Rating (\d+) \(시장 대비 부진\)$/, "RS Rating $1 (lagging market)"],
        // "5/5년 흑자"
        [/^(\d+)\/(\d+)년 흑자$/, "$1/$2 years profitable"],
        // "3/5년"
        [/^(\d+)\/(\d+)년$/, "$1/$2 years"],
        // "12.5%/년"
        [/^(.+)%\/년$/, "$1%/yr"],
        // "ROE >= 15% (섹터 기준)"
        [/^ROE >= ([\d.]+)% \(섹터 기준\)$/, "ROE >= $1% (sector benchmark)"],
        [/^부채비율 <= ([\d.]+)% \(섹터 기준\)$/, "Debt-to-equity <= $1% (sector benchmark)"],
        [/^영업이익률 >= ([\d.]+)% \(섹터 기준\)$/, "Operating margin >= $1% (sector benchmark)"],
        [/^매출총이익률 >= ([\d.]+)% \(R&D 여력\)$/, "Gross margin >= $1% (R&D capacity)"],
        [/^순이익률 >= ([\d.]+)% \(섹터 기준\)$/, "Net margin >= $1% (sector benchmark)"],
        [/^R&D 투자 \(매출 대비 ([\d.]+)%\+\)$/, "R&D investment (≥$1% of revenue)"],
        // "20.5% (기준 20%)"
        [/^(.+) \(기준 (.+)\)$/, "$1 (target $2)"],
        // "+12.5% (기준 +30%)"
        // 기간 표시 "Tech — 해당 없음" 등 (이미 정확 매칭)
        // "재무품질 양호 (85/100)"
        [/^재무품질 양호 \((\d+)\/100\)$/, "Financial quality healthy ($1/100)"],
        [/^재무품질 우려 \((\d+)\/100\)$/, "Financial quality concerns ($1/100)"],
        // "평균 25.3% · 편차 2.1%p"
        [/^평균 ([\d.]+)% · 편차 ([\d.]+)%p$/, "Avg $1% · std $2pp"],
        // "적정가 대비 +15% 저평가"
        [/^적정가 대비 ([+-]?[\d.]+)% 저평가$/, "$1% undervalued vs fair value"],
        [/^적정가 대비 ([+-]?[\d.]+)% 고평가$/, "$1% overvalued vs fair value"],
        [/^적정가 대비 ([+-]?[\d.]+)%$/, "$1% vs fair value"],
        // 옵션 텍스트
        [/^현재가 대비 ([\d.]+)% 위 - 이 가격까지 상승 베팅$/, "$1% above current — upside bet to this strike"],
        [/^현재가 대비 ([\d.]+)% 아래 - 이 가격까지 하락 베팅$/, "$1% below current — downside bet to this strike"],
        [/^현재가 대비 ([\d.]+)% 위 - 하락 헤지 포지션$/, "$1% above current — downside hedge position"],
        [/^현재가 대비 ([\d.]+)% 아래 - ITM 콜 \(이미 수익\)$/, "$1% below current — ITM call (already in profit)"],
        [/^현재가보다 ([\d.]+)% 위 - 주가 상승 압력$/, "$1% above current — upward price pressure"],
        [/^현재가보다 ([\d.]+)% 아래 - 주가 하락 압력$/, "$1% below current — downward price pressure"],
        // 거래량 표시 "10.5일 (높음)" 같은
        [/^([\d.]+)일\(([^)]+)\)$/, "$1d ($2)"],
        [/^([\d.]+)일 \(([^)]+)\)$/, "$1d ($2)"],
    ];

    function translateBackend(text) {
        if (!text || typeof text !== 'string') return text;
        const lang = getLang();
        if (lang !== 'en') return text;
        const trimmed = text.trim();
        if (!trimmed) return text;
        // 정확 매칭
        if (BACKEND_TEXT_MAP[trimmed]) {
            return text.replace(trimmed, BACKEND_TEXT_MAP[trimmed]);
        }
        // 패턴 매칭
        for (let i = 0; i < BACKEND_PATTERNS.length; i++) {
            const m = trimmed.match(BACKEND_PATTERNS[i][0]);
            if (m) {
                let replaced = BACKEND_PATTERNS[i][1];
                for (let g = 1; g < m.length; g++) {
                    replaced = replaced.split('$' + g).join(m[g]);
                }
                return text.replace(trimmed, replaced);
            }
        }
        return text;
    }

    // ===== MutationObserver — 새로 추가된 DOM 텍스트 자동 번역 =====
    // 영어 모드일 때만 동작. JS가 그려준 분석 카드 등을 자동 영어화.
    // 무한 loop 방지: 번역 완료 노드는 WeakSet에 마킹.
    const TRANSLATED_NODES = new WeakSet();

    function translateNode(node) {
        if (!node || TRANSLATED_NODES.has(node)) return;
        if (node.nodeType === 3) { // TEXT_NODE
            const original = node.textContent;
            const translated = translateBackend(original);
            if (translated !== original) {
                TRANSLATED_NODES.add(node);
                node.textContent = translated;
            }
        } else if (node.nodeType === 1) { // ELEMENT_NODE
            // script/style은 건드리지 않음
            const tag = (node.tagName || '').toUpperCase();
            if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'CODE') return;
            // 자식 노드 재귀 처리
            const children = node.childNodes;
            for (let i = 0; i < children.length; i++) {
                translateNode(children[i]);
            }
        }
    }

    function startBackendObserver() {
        if (getLang() !== 'en') return;
        // 초기 페이지 전체 한 번 변환
        translateNode(document.body);
        // MutationObserver 등록 — childList만 (characterData는 무한 loop 위험)
        if (!window.MutationObserver) return;
        const obs = new MutationObserver(function (mutations) {
            mutations.forEach(function (m) {
                m.addedNodes.forEach(function (n) {
                    translateNode(n);
                });
            });
        });
        obs.observe(document.body, {
            childList: true,
            subtree: true,
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startBackendObserver);
    } else {
        startBackendObserver();
    }

    // ===== 전역 노출 =====
    global.t = t;
    global.applyI18n = applyI18n;
    global.setLang = setLang;
    global.getLang = getLang;
    global.I18N_DICT = I18N_DICT;
    global.translateBackend = translateBackend;
})(window);
