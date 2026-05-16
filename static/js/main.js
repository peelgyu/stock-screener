/* ============================================================
 * StockInto 메인 JS — index.html에서 추출 (리팩터 2/4)
 * 분리되지 않은 단일 번들. 다음 PR에서 책임별로 쪼갤 예정.
 * ============================================================ */
        const input = document.getElementById('tickerInput');
        const btn = document.getElementById('searchBtn');
        const loading = document.getElementById('loading');
        const errorMsg = document.getElementById('errorMsg');
        const results = document.getElementById('results');
        const acBox = document.getElementById('autocomplete');
        let acTimeout = null;
        let acIndex = -1;
        let chartInstances = [];
        let currentTicker = null;
        let currentStockName = null;
        let optionsLoaded = false;
        let krxLoaded = false;
        let newsLoaded = false;

        // ========== 일일 브리핑 모달 ==========
        const BRIEFING_KEY_LAST = 'stockinto_briefing_last_shown';
        const BRIEFING_KEY_NEVER = 'stockinto_briefing_never_again';

        function todayKST() {
            // KST 기준 YYYY-MM-DD
            const now = new Date(Date.now() + 9*3600*1000);
            return now.toISOString().slice(0, 10);
        }

        function briefingPeriodKey() {
            // 갱신 키 — KST 08:30 / 16:00 두 컷오프 적용
            // dawn(00:00~08:30) → 어제_pm   (어제 오후 시점 마지막 갱신)
            // morning(08:30~16:00) → 오늘_am
            // afternoon(≥16:00) → 오늘_pm  (한국장 마감 직후 갱신)
            // 컷오프 넘어가면 키 자동 변경 → 모달 다시 뜸
            const nowKST = new Date(Date.now() + 9*3600*1000);
            const totalMin = nowKST.getUTCHours() * 60 + nowKST.getUTCMinutes();
            let suffix;
            if (totalMin < 8 * 60 + 30) {
                nowKST.setUTCDate(nowKST.getUTCDate() - 1);
                suffix = 'pm';
            } else if (totalMin < 16 * 60) {
                suffix = 'am';
            } else {
                suffix = 'pm';
            }
            return nowKST.toISOString().slice(0, 10) + '_' + suffix;
        }

        function shouldShowBriefingModal() {
            try {
                if (localStorage.getItem(BRIEFING_KEY_NEVER) === '1') return false;
                const last = localStorage.getItem(BRIEFING_KEY_LAST);
                return last !== briefingPeriodKey();
            } catch (e) { return false; }
        }

        function dontShowBriefingToday() {
            try {
                const checkbox = document.getElementById('briefingNeverAgain');
                if (checkbox && checkbox.checked) {
                    localStorage.setItem(BRIEFING_KEY_NEVER, '1');
                } else {
                    localStorage.setItem(BRIEFING_KEY_LAST, briefingPeriodKey());
                }
            } catch (e) {}
            closeBriefingModal();
        }

        function closeBriefingModal() {
            const m = document.getElementById('briefingModalBackdrop');
            if (m) m.style.display = 'none';
            // 닫기 = "이 갱신 주기 봤음"으로 기록 (X·백드롭·ESC 모두)
            try { localStorage.setItem(BRIEFING_KEY_LAST, briefingPeriodKey()); } catch (e) {}
        }

        function fmtIdxRow(name, idx) {
            if (!idx) return `<div class="briefing-modal-idx"><div class="name">${name}</div><div class="value" style="color:#666;">—</div></div>`;
            const cls = idx.change_pct > 0 ? 'up' : idx.change_pct < 0 ? 'down' : '';
            const arrow = idx.change_pct > 0 ? '▲' : idx.change_pct < 0 ? '▼' : '─';
            const valStr = Number(idx.value).toLocaleString('ko-KR', {minimumFractionDigits:2, maximumFractionDigits:2});
            const pctStr = (idx.change_pct >= 0 ? '+' : '') + idx.change_pct.toFixed(2);
            return `<div class="briefing-modal-idx">
                <div class="name">${name}</div>
                <div class="value">${valStr}</div>
                <div class="change ${cls}">${arrow} ${pctStr}%</div>
            </div>`;
        }

        async function showBriefingModal() {
            if (!shouldShowBriefingModal()) return;
            const backdrop = document.getElementById('briefingModalBackdrop');
            if (!backdrop) return;
            backdrop.style.display = 'flex';

            try {
                const res = await fetch('/api/briefing/summary');
                const data = await res.json();
                if (!data.available) {
                    backdrop.style.display = 'none';
                    return;
                }
                renderBriefingModal(data);
            } catch (e) {
                backdrop.style.display = 'none';
            }
        }

        function escapeBriefHtml(s) {
            return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        function renderBriefingModal(data) {
            const titleEl = document.getElementById('briefingModalTitle');
            const dateEl = document.getElementById('briefingModalDate');
            const bodyEl = document.getElementById('briefingModalBody');
            if (titleEl && data.title_kr) titleEl.textContent = data.title_kr;
            if (dateEl) {
                const usClose = escapeBriefHtml(data.us_close_kst || '—');
                const krClose = escapeBriefHtml(data.kr_close_kst || '—');
                dateEl.innerHTML = `📅 ${data.date} (${data.weekday_kr || ''}) · 한국시간 기준
                    <div class="briefing-modal-close-times">
                        <span>🇺🇸 미국 마감: <strong>${usClose}</strong></span>
                        <span>🇰🇷 한국 마감: <strong>${krClose}</strong></span>
                    </div>`;
            }

            const us = data.us_indices || {};
            const kr = data.kr_indices || {};
            const fx = data.fx || {};
            const fg = data.fear_greed || {};

            const indicesHTML = `
                <div class="briefing-modal-indices">
                    ${fmtIdxRow('S&P 500', us.sp500)}
                    ${fmtIdxRow('NASDAQ', us.nasdaq)}
                    ${fmtIdxRow('KOSPI', kr.kospi)}
                    ${fmtIdxRow('KOSDAQ', kr.kosdaq)}
                </div>`;

            const fxStr = fx.usd_krw ? '₩' + Math.round(fx.usd_krw).toLocaleString('ko-KR') : '—';
            const fxTime = fx.fetched_at ? `<div style="font-size:0.6rem;color:#999;margin-top:2px;">${escapeBriefHtml(fx.fetched_at)}</div>` : '';
            const fgScore = fg.score != null ? fg.score : '—';
            const fgLabel = fg.label || '';
            const fgColor = fgScore < 25 ? '#f44336' : fgScore < 55 ? '#fbbf24' : '#4caf50';

            const fgRow = `
                <div class="briefing-modal-fg-row">
                    <div>
                        <div style="font-size:0.7rem;color:#888;">USD/KRW</div>
                        <div style="font-size:0.95rem;font-weight:700;">${fxStr}</div>
                        ${fxTime}
                    </div>
                    <div>
                        <div style="font-size:0.7rem;color:#888;">공포탐욕</div>
                        <div style="font-size:0.95rem;font-weight:700;color:${fgColor};">${fgScore} <span style="font-size:0.68rem;color:#888;font-weight:400;">${escapeBriefHtml(fgLabel)}</span></div>
                    </div>
                </div>`;

            const newsKR = (data.top_news_kr || []).slice(0, 3);
            let newsHTML = '';
            if (newsKR.length) {
                newsHTML = '<div class="briefing-modal-news"><div class="briefing-modal-news-title">📰 주요 뉴스</div>';
                newsKR.forEach(n => {
                    const link = n.link || n.originalLink || '#';
                    newsHTML += `<a href="${escapeBriefHtml(link)}" target="_blank" rel="noopener" class="briefing-modal-news-item">
                        <div>${escapeBriefHtml((n.title || '').slice(0, 65))}</div>
                        <div class="src">${escapeBriefHtml(n.source || '')}</div>
                    </a>`;
                });
                newsHTML += '</div>';
            }

            bodyEl.innerHTML = indicesHTML + fgRow + newsHTML;
        }

        // 백드롭 클릭 + ESC 키 닫기
        document.addEventListener('DOMContentLoaded', () => {
            const backdrop = document.getElementById('briefingModalBackdrop');
            if (backdrop) {
                backdrop.addEventListener('click', (e) => {
                    if (e.target === backdrop) closeBriefingModal();
                });
            }
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    const m = document.getElementById('briefingModalBackdrop');
                    if (m && m.style.display === 'flex') closeBriefingModal();
                }
            });
            // 페이지 로드 후 1초 뒤 모달 표시 (메인 분석 페이지 로딩 안 거슬리게)
            setTimeout(showBriefingModal, 1000);
        });

        // ========== 용어 툴팁 헬퍼 ==========
        // tt('PER') → '<span class="term-tooltip" data-term="PER">PER</span>'
        // tt('FCF / 순이익') → 텍스트 안의 모든 등록된 용어를 자동 마킹
        function tt(text) {
            return (window.StockIntoTooltip && text != null) ? window.StockIntoTooltip.markup(String(text)) : text;
        }

        // ========== 관심 종목 + 최근 검색 (localStorage 기반) ==========
        const FAV_KEY = 'stockinto_favorites_v1';
        const HIST_KEY = 'stockinto_history_v1';
        const MAX_FAV = 30;
        const MAX_HIST = 8;

        function getFavs() { try { return JSON.parse(localStorage.getItem(FAV_KEY) || '[]'); } catch(e){ return []; } }
        function setFavs(list) { localStorage.setItem(FAV_KEY, JSON.stringify(list.slice(0, MAX_FAV))); renderFavorites(); }
        function getHist() { try { return JSON.parse(localStorage.getItem(HIST_KEY) || '[]'); } catch(e){ return []; } }
        function setHist(list) { localStorage.setItem(HIST_KEY, JSON.stringify(list.slice(0, MAX_HIST))); renderHistory(); }

        function isFav(ticker) { return getFavs().some(f => f.ticker === ticker); }

        function toggleFavorite() {
            if (!currentTicker) return;
            const favs = getFavs();
            const idx = favs.findIndex(f => f.ticker === currentTicker);
            if (idx >= 0) { favs.splice(idx, 1); }
            else { favs.unshift({ ticker: currentTicker, name: currentStockName || currentTicker, ts: Date.now() }); }
            setFavs(favs);
            updateFavBtn();
        }

        function updateFavBtn() {
            const btn = document.getElementById('favBtn');
            if (!btn) return;
            const on = isFav(currentTicker);
            btn.textContent = on ? '⭐ 관심 종목 해제' : '☆ 관심 종목 추가';
            btn.style.background = on ? 'rgba(245,158,11,0.15)' : 'transparent';
            btn.style.color = on ? '#fbbf24' : 'var(--text-secondary)';
            btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        }

        function pushHistory(ticker, name) {
            if (!ticker) return;
            const list = getHist().filter(h => h.ticker !== ticker);
            list.unshift({ ticker, name: name || ticker, ts: Date.now() });
            setHist(list);
        }

        function renderFavorites() {
            const sec = document.getElementById('favoritesSection');
            const list = document.getElementById('favoritesList');
            const favs = getFavs();
            if (favs.length === 0) { sec.style.display = 'none'; return; }
            sec.style.display = '';
            list.innerHTML = favs.map(f =>
                `<button class="quick-btn" data-action="quickSearch" data-ticker="${escapeHtml(f.ticker.replace(/'/g,''))}" title="${escapeHtml(f.name)}">⭐ ${escapeHtml(f.name)}</button>`
            ).join('');
        }

        function renderHistory() {
            const sec = document.getElementById('historySection');
            const list = document.getElementById('historyList');
            const hist = getHist();
            if (hist.length === 0) { sec.style.display = 'none'; return; }
            sec.style.display = '';
            list.innerHTML = hist.map(h =>
                `<button class="quick-btn" data-action="quickSearch" data-ticker="${escapeHtml(h.ticker.replace(/'/g,''))}" title="${escapeHtml(h.name)}">${escapeHtml(h.name)}</button>`
            ).join('');
        }

        function clearHistory() {
            if (!confirm('최근 본 종목 기록을 모두 지울까요?')) return;
            localStorage.removeItem(HIST_KEY);
            renderHistory();
        }

        function shareStock() {
            if (!currentTicker) return;
            const url = `${location.origin}/?q=${encodeURIComponent(currentTicker)}`;
            const title = `${currentStockName} 분석 - StockInto`;
            if (navigator.share) {
                navigator.share({ title, url, text: `${currentStockName} 종목 분석 결과 보기` }).catch(()=>{});
            } else {
                navigator.clipboard.writeText(url).then(() => {
                    alert('🔗 링크 복사 완료!\n' + url);
                }).catch(() => {
                    prompt('링크 복사:', url);
                });
            }
        }

        // 페이지 로드 시 관심·히스토리 표시
        renderFavorites();
        renderHistory();

        // URL 쿼리(?q=AAPL) 또는 /stock/{ticker} 라우트로 진입 시 자동 검색
        (function() {
            const params = new URLSearchParams(location.search);
            const q = params.get('q') || params.get('ticker') || (document.body.dataset.autoTicker || '');
            if (q) {
                setTimeout(() => {
                    const inp = document.getElementById('tickerInput');
                    if (inp) { inp.value = q; analyze(); }
                }, 100);
            }
        })();

        // PWA Service Worker 등록
        if ('serviceWorker' in navigator) {
            window.addEventListener('load', () => {
                navigator.serviceWorker.register('/sw.js').catch(() => {});
            });
        }

        // 설치 유도 (Android Chrome)
        let deferredPrompt = null;
        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            deferredPrompt = e;
            const btn = document.getElementById('installBtn');
            if (btn) btn.style.display = 'inline-flex';
        });
        function triggerInstall() {
            if (!deferredPrompt) {
                window.location.href = '/install';
                return;
            }
            deferredPrompt.prompt();
            deferredPrompt.userChoice.then(() => {
                deferredPrompt = null;
                const btn = document.getElementById('installBtn');
                if (btn) btn.style.display = 'none';
            });
        }
        window.addEventListener('appinstalled', () => {
            const btn = document.getElementById('installBtn');
            if (btn) btn.style.display = 'none';
        });

        // 거래량 TOP 10 사이드바
        let mostActiveData = null;
        async function loadMostActive(force=false) {
            if (!force && mostActiveData) return;
            try {
                const res = await fetch('/api/most_active');
                const data = await res.json();
                mostActiveData = data;
                renderVS('us', data.us || []);
                renderVS('kr', data.kr || []);
            } catch(e) {
                ['us','kr'].forEach(m => {
                    document.getElementById('vsList'+m.charAt(0).toUpperCase()+m.slice(1))
                        .innerHTML = '<div style="text-align:center;color:#666;padding:20px;font-size:0.75rem;">로드 실패</div>';
                });
            }
        }

        function renderVS(market, items) {
            const el = document.getElementById('vsList' + market.charAt(0).toUpperCase() + market.slice(1));
            if (!items || items.length === 0) {
                el.innerHTML = '<div style="text-align:center;color:#666;padding:20px;font-size:0.75rem;">데이터 없음</div>';
                return;
            }
            el.innerHTML = items.map((item, i) => {
                const changeClass = item.change_pct > 0 ? 'up' : item.change_pct < 0 ? 'down' : 'flat';
                const sign = item.change_pct >= 0 ? '+' : '';
                const priceStr = market === 'kr'
                    ? '₩' + Math.round(item.price).toLocaleString()
                    : '$' + item.price.toFixed(2);
                const volStr = item.volume >= 1e6 ? (item.volume/1e6).toFixed(1)+'M'
                    : item.volume >= 1e3 ? (item.volume/1e3).toFixed(0)+'K' : item.volume;
                const displayTicker = item.display_ticker || item.ticker;
                return `<div class="vs-item" data-action="vsQuickAnalyze" data-ticker="${item.ticker}">
                    <div class="vs-rank">${i+1}</div>
                    <div class="vs-main">
                        <div class="vs-ticker">${displayTicker}</div>
                        <div class="vs-name">${item.name} · ${volStr}</div>
                    </div>
                    <div class="vs-right">
                        <div class="vs-price">${priceStr}</div>
                        <div class="vs-change ${changeClass}">${sign}${item.change_pct}%</div>
                    </div>
                </div>`;
            }).join('');
        }

        function switchVSTab(market) {
            document.querySelectorAll('.vs-tab').forEach(t => t.classList.toggle('active', t.dataset.market === market));
            document.querySelectorAll('.vs-list').forEach(l => l.classList.remove('active'));
            document.getElementById('vsList' + market.charAt(0).toUpperCase() + market.slice(1)).classList.add('active');
        }

        function vsQuickAnalyze(ticker) {
            input.value = ticker;
            acBox.classList.remove('show');
            analyze();
            // 모바일에선 사이드바 닫기
            document.getElementById('volumeSidebar').classList.remove('open');
        }

        function toggleVolumeSidebar() {
            document.getElementById('volumeSidebar').classList.toggle('open');
        }

        // 페이지 로드 시 거래량 TOP 자동 로드
        window.addEventListener('load', () => loadMostActive());

        // 이용 동의 모달 (localStorage로 한 번만 표시)
        (function initConsent() {
            const KEY = 'ss_consent_v1';
            if (!localStorage.getItem(KEY)) {
                document.getElementById('consentOverlay').classList.add('show');
            }
        })();
        function acceptConsent() {
            localStorage.setItem('ss_consent_v1', new Date().toISOString());
            document.getElementById('consentOverlay').classList.remove('show');
        }

        input.addEventListener('keydown', (e) => {
            const items = acBox.querySelectorAll('.ac-item');
            if (e.key === 'ArrowDown') { e.preventDefault(); acIndex = Math.min(acIndex + 1, items.length - 1); items.forEach((el, i) => el.classList.toggle('selected', i === acIndex)); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); acIndex = Math.max(acIndex - 1, -1); items.forEach((el, i) => el.classList.toggle('selected', i === acIndex)); }
            else if (e.key === 'Enter') { if (acIndex >= 0 && items[acIndex]) items[acIndex].click(); else { acBox.classList.remove('show'); analyze(); } }
            else if (e.key === 'Escape') acBox.classList.remove('show');
        });

        input.addEventListener('input', () => {
            clearTimeout(acTimeout);
            const q = input.value.trim();
            if (q.length < 1) { acBox.classList.remove('show'); return; }
            acTimeout = setTimeout(() => searchAutocomplete(q), 250);
        });

        document.addEventListener('click', (e) => { if (!e.target.closest('.search-wrap')) acBox.classList.remove('show'); });

        async function searchAutocomplete(q) {
            try {
                const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
                const data = await res.json();
                if (data.length === 0) { acBox.classList.remove('show'); return; }
                acIndex = -1;
                acBox.innerHTML = data.map(item => {
                    const sub = [item.sector || '', item.engName || ''].filter(Boolean).join(' · ');
                    return `
                        <div class="ac-item" data-symbol="${item.symbol}">
                            <div>
                                <div class="ac-name">${item.name}</div>
                                ${sub ? `<div class="ac-sub">${sub}</div>` : ''}
                            </div>
                            <div class="ac-right">
                                <span class="ac-symbol">${item.symbol}</span>
                                <span class="ac-exchange">${item.exchange || ''}</span>
                            </div>
                        </div>`;
                }).join('');
                acBox.querySelectorAll('.ac-item').forEach(el => {
                    el.addEventListener('click', () => { input.value = el.dataset.symbol; acBox.classList.remove('show'); analyze(); });
                });
                acBox.classList.add('show');
            } catch (e) {}
        }

        function quickSearch(ticker) { input.value = ticker; acBox.classList.remove('show'); analyze(); }

        function switchTab(tab) {
            // tab-btn 순서: investors, trend, krx(숨김 가능), sentiment, positions, options
            // 탭 활성화는 id로 직접 매핑 (인덱스 의존 제거)
            document.querySelectorAll('.tab-btn').forEach(b => {
                const id = b.id || '';
                const isActive = id === `tabbtn-${tab}`;
                b.classList.toggle('active', isActive);
                b.setAttribute('aria-selected', isActive ? 'true' : 'false');
            });
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            const target = document.getElementById(`tab-${tab}`);
            if (target) target.classList.add('active');
            if (tab === 'options' && !optionsLoaded && currentTicker) loadOptionsLazy();
            if (tab === 'krx' && !krxLoaded && currentTicker) loadKRXLazy();
            if (tab === 'news' && !newsLoaded && currentTicker) loadNewsLazy();
        }

        async function loadOptionsLazy() {
            optionsLoaded = true;
            const el = document.getElementById('optCard');
            el.innerHTML = `<div style="text-align:center;padding:40px;color:#888;"><div class="spinner" style="margin:0 auto 12px;"></div>옵션 체인 로딩...</div>`;
            try {
                const res = await fetch('/api/options', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticker: currentTicker }) });
                const opt = await res.json();
                renderOptions(opt);
            } catch (e) {
                el.innerHTML = `<div style="color:#888;padding:40px;text-align:center;">옵션 데이터 로드 실패</div>`;
                optionsLoaded = false;
            }
        }

        async function loadNewsLazy() {
            newsLoaded = true;
            const el = document.getElementById('newsCard');
            el.innerHTML = `<div style="text-align:center;padding:40px;color:#888;"><div class="spinner" style="margin:0 auto 12px;"></div>관련 뉴스 검색 중...</div>`;
            try {
                const res = await fetch('/api/news', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticker: currentTicker }) });
                const news = await res.json();
                renderNews(news);
                if (!news || !news.available) newsLoaded = false;
            } catch (e) {
                renderNews({available: false, error: '네트워크 오류 — 다시 시도해 주세요.'});
                newsLoaded = false;
            }
        }

        function escapeHtml(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }

        function timeAgoKR(rfc822) {
            try {
                const d = new Date(rfc822);
                if (isNaN(d.getTime())) return '';
                const diffMs = Date.now() - d.getTime();
                const m = Math.floor(diffMs / 60000);
                if (m < 1) return '방금 전';
                if (m < 60) return `${m}분 전`;
                const h = Math.floor(m / 60);
                if (h < 24) return `${h}시간 전`;
                const dd = Math.floor(h / 24);
                if (dd < 7) return `${dd}일 전`;
                return d.toLocaleDateString('ko-KR');
            } catch (e) { return ''; }
        }

        function renderNews(news) {
            const el = document.getElementById('newsCard');
            if (!news || !news.available) {
                const errMsg = (news && news.error) ? news.error : '뉴스 데이터를 받지 못했습니다.';
                el.innerHTML = `
                    <div style="color:#888;padding:36px 20px;text-align:center;">
                        <div style="font-size:1.05rem;margin-bottom:8px;">📰 뉴스 일시 불가</div>
                        <div style="font-size:0.85rem;color:#666;margin-bottom:18px;">${escapeHtml(errMsg)}</div>
                        <button data-action="retryNews" style="padding:10px 18px;min-height:44px;border-radius:9999px;border:1px solid var(--border);background:transparent;color:var(--accent-cyan);cursor:pointer;font-size:0.85rem;font-weight:600;font-family:inherit;">🔄 다시 시도</button>
                    </div>`;
                return;
            }
            const items = news.items || [];
            if (items.length === 0) {
                el.innerHTML = `<div style="color:#888;padding:36px 20px;text-align:center;">관련 뉴스가 없습니다.</div>`;
                return;
            }
            const list = items.map(it => {
                const link = it.link || it.originalLink || '#';
                const title = escapeHtml(it.title);
                const desc = escapeHtml(it.description);
                const source = escapeHtml(it.source || '');
                const ago = escapeHtml(timeAgoKR(it.pubDate));
                return `
                    <a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer"
                       style="display:block;padding:14px 16px;border:1px solid var(--border);border-radius:12px;margin-bottom:10px;text-decoration:none;color:inherit;background:var(--card);transition:transform .12s ease, border-color .12s ease;">
                        <div style="font-size:0.95rem;font-weight:600;line-height:1.45;margin-bottom:6px;color:var(--text);">${title}</div>
                        <div style="font-size:0.82rem;color:#888;line-height:1.5;margin-bottom:8px;">${desc}</div>
                        <div style="font-size:0.72rem;color:#666;display:flex;gap:8px;align-items:center;">
                            <span style="color:var(--accent-cyan);font-weight:600;">${source}</span>
                            <span>·</span>
                            <span>${ago}</span>
                        </div>
                    </a>`;
            }).join('');
            const note = `
                <div style="font-size:0.7rem;color:#666;text-align:center;margin-top:14px;line-height:1.6;font-style:italic;">
                    검색어: "${escapeHtml(news.query || '')}" · 출처: 네이버 검색 API · 6시간 캐시<br>
                    뉴스 본문 저작권은 각 언론사에 있으며, 클릭 시 원문 사이트로 이동합니다.
                </div>`;
            el.innerHTML = `<div class="section-title" style="margin-top:0;">📰 관련 뉴스 (최신순 ${items.length}건)</div>${list}${note}`;
        }

        async function loadKRXLazy() {
            krxLoaded = true;
            const el = document.getElementById('krxCard');
            el.innerHTML = `<div style="text-align:center;padding:40px;color:#888;"><div class="spinner" style="margin:0 auto 12px;"></div>KRX 수급 데이터 로딩... (최대 8초)</div>`;
            try {
                const res = await fetch('/api/krx', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticker: currentTicker }) });
                const krx = await res.json();
                // renderKRX는 available:false 응답도 탭 유지하면서 에러 카드 표시
                renderKRX(krx, true);
                // 응답 자체가 실패면 다음에 다시 시도할 수 있게 플래그 리셋
                if (!krx || !krx.available) krxLoaded = false;
            } catch (e) {
                renderKRX({available: false, error: '네트워크 오류 — 다시 시도해 주세요.'}, true);
                krxLoaded = false;
            }
        }

        async function analyze() {
            const query = input.value.trim();
            if (!query) return;
            btn.disabled = true;
            loading.style.display = 'block';
            errorMsg.style.display = 'none';
            results.style.display = 'none';
            chartInstances.forEach(c => { try { c.destroy(); } catch(e){} });
            chartInstances = [];
            optionsLoaded = false;
            krxLoaded = false;
            newsLoaded = false;
            try {
                const res = await fetch('/api/analyze?_=' + Date.now(), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-cache' },
                    body: JSON.stringify({ ticker: query })
                });
                let data = null;
                try { data = await res.json(); } catch (e) { /* ignore */ }
                if (!res.ok) {
                    errorMsg.textContent = (data && data.error) ? data.error : `서버 오류 (HTTP ${res.status})`;
                    errorMsg.style.display = 'block';
                    return;
                }
                if (!data) {
                    errorMsg.textContent = '서버 응답이 비어있습니다. 잠시 후 다시 시도해주세요.';
                    errorMsg.style.display = 'block';
                    return;
                }
                renderResults(data);
                results.style.display = 'block';
            } catch (err) {
                errorMsg.textContent = '네트워크 오류: ' + (err && err.message ? err.message : '알 수 없음') + ' — 새로고침(Ctrl+Shift+R)을 시도해주세요.';
                errorMsg.style.display = 'block';
            } finally {
                btn.disabled = false;
                loading.style.display = 'none';
            }
        }

        function getFgColor(s) { if (s >= 75) return '#2e7d32'; if (s >= 55) return '#66bb6a'; if (s >= 45) return '#ffeb3b'; if (s >= 25) return '#ff9800'; return '#e53935'; }
        function getBarColor(s) { if (s >= 60) return '#4caf50'; if (s >= 40) return '#ffeb3b'; return '#f44336'; }

        function renderResults(data) {
            currentTicker = data.ticker;
            currentStockName = data.stock.name || data.ticker;
            // 검색 시점에 최근 본 종목에 추가
            pushHistory(data.ticker, data.stock.name || data.ticker);
            renderMarketBanner(data.marketRegime);
            renderVerdict(data.verdict);
            renderDataWarnings(data.dataWarnings);
            const analyzedAt = new Date();
            const tsKR = analyzedAt.toLocaleString('ko-KR', {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'});
            // HTML escape (description은 외부 데이터 — XSS 방어)
            const escHTML = (s) => String(s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            const descHTML = data.stock.description
                ? `<div style="margin-top:6px;font-size:0.85rem;line-height:1.5;color:#bbb;">📝 ${escHTML(data.stock.description)}</div>`
                : '';
            const meta = data.dataMeta || {};
            const finEndDate = meta.financialEndDate ? `<span title="공시 기준일 — 분석에 사용된 재무 데이터가 보고된 시점">📊 재무 ${escHTML(meta.financialEndDate)} (${escHTML(meta.financialPeriodType || '')})</span>` : '';
            const finSource = meta.financialSourceShort ? `<span title="${escHTML(meta.financialSource || '')}">🏛 ${escHTML(meta.financialSourceShort)}</span>` : '';
            document.getElementById('stockCard').innerHTML = `
                <div class="stock-name">${escHTML(data.stock.name)}<span class="stock-ticker">${escHTML(data.ticker)}</span></div>
                <div class="stock-meta">
                    <span>${escHTML(data.stock.sector)}</span>
                    <span>${escHTML(data.stock.industry)}</span>
                    <span>${escHTML(data.stock.price)}</span>
                    <span>시총 ${escHTML(data.stock.marketCap)}</span>
                </div>
                ${descHTML}
                <div style="display:flex;gap:10px;flex-wrap:wrap;font-size:0.7rem;color:#777;margin-top:6px;align-items:center;">
                    <span title="시세는 거래소 직접 연동이 아닌 무료 데이터 소스 기준 — 거의 모든 무료 주식 사이트가 동일">⏱ 시세 ${meta.priceDelayMinutes||15}분 지연</span>
                    ${finEndDate}
                    ${finSource}
                    <span>· 분석 ${meta.analysisTimeKST || tsKR}</span>
                </div>
                <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;">
                    <button id="favBtn" data-action="toggleFavorite" aria-pressed="false" style="padding:11px 18px;min-height:44px;border-radius:9999px;border:1px solid var(--border);background:transparent;color:var(--text-secondary);cursor:pointer;font-size:0.82rem;font-weight:600;font-family:inherit;transition:all 0.15s;">☆ 관심 종목 추가</button>
                    <button data-action="shareStock" style="padding:11px 18px;min-height:44px;border-radius:9999px;border:1px solid var(--border);background:transparent;color:var(--text-secondary);cursor:pointer;font-size:0.82rem;font-weight:600;font-family:inherit;transition:all 0.15s;" aria-label="이 종목 분석 링크 공유">🔗 공유</button>
                </div>`;
            updateFavBtn();
            window._latestDataMeta = data.dataMeta || {};
            renderTVChart(data.ticker);
            renderFairValue(data.fairValue);
            renderRSRating(data.rsRating);
            renderFearGreed(data.fearGreed);
            renderPositions(data.positions);
            if (data.options && data.options.lazy) {
                document.getElementById('optCard').innerHTML = `<div style="color:#888;padding:40px;text-align:center;">옵션 탭을 클릭하면 데이터를 불러옵니다.</div>`;
            } else {
                renderOptions(data.options);
            }
            renderOverall(data.overall);
            renderInvestors(data.investors, data.dataMeta);
            renderQuality(data.quality);
            const isKR = (data.ticker || '').endsWith('.KS') || (data.ticker || '').endsWith('.KQ');
            renderTrendCharts(data.history, isKR ? 'KRW' : 'USD');
            renderKRX(data.krx, isKR);
        }

        function tvSymbol(ticker) {
            // TradingView 심볼 변환
            // 한국 코스피: KRX:005930 (TradingView가 KRX 거래소 코드로 인식)
            // 한국 코스닥: KOSDAQ:240810 (별도 거래소 식별자)
            // 미국·해외: 그대로 (TradingView가 자동 인식)
            if (!ticker) return 'NASDAQ:AAPL';  // 빈 값 폴백 (안전망)
            const t = String(ticker).trim().toUpperCase();
            if (t.endsWith('.KS')) return 'KRX:' + t.replace(/\.KS$/, '');
            if (t.endsWith('.KQ')) return 'KOSDAQ:' + t.replace(/\.KQ$/, '');
            if (/^\d{6}$/.test(t)) return 'KRX:' + t;  // 6자리 숫자만 들어왔을 때
            return t;
        }

        function renderTVChart(ticker) {
            const el = document.getElementById('tvChartCard');
            if (!el) return;
            const symbol = tvSymbol(ticker);
            el.innerHTML = '';
            const containerId = 'tvChart_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8);
            // 보이기 전엔 placeholder (페이지 초기 로딩 빠르게)
            el.innerHTML = `
                <div class="tv-card">
                    <div class="tv-card-title">📊 주가 차트 · <strong>${symbol}</strong></div>
                    <div class="tv-chart-wrap"><div id="${containerId}" style="height:100%;width:100%;display:flex;align-items:center;justify-content:center;color:#888;font-size:0.9rem;">차트 로딩 대기중... (스크롤하면 즉시 표시)</div></div>
                </div>`;

            if (typeof TradingView === 'undefined') {
                el.querySelector('.tv-chart-wrap').innerHTML =
                    '<div style="color:#888;text-align:center;padding:40px;">차트 라이브러리 로드 실패 — 새로고침 해주세요</div>';
                return;
            }

            const targetEl = document.getElementById(containerId);
            if (!targetEl) return;

            // Intersection Observer로 화면에 들어올 때만 위젯 생성
            const loadWidget = () => {
                if (!document.getElementById(containerId)) return;
                targetEl.innerHTML = '';   // placeholder 제거
                try {
                    new TradingView.widget({
                        autosize: true,
                        symbol: symbol,
                        interval: 'D',
                        timezone: 'Asia/Seoul',
                        theme: 'dark',
                        style: '1',
                        locale: 'kr',
                        toolbar_bg: '#1a1a2e',
                        enable_publishing: false,
                        hide_side_toolbar: false,
                        allow_symbol_change: false,
                        container_id: containerId,
                        studies: ['MASimple@tv-basicstudies', 'Volume@tv-basicstudies'],
                        save_image: false,
                    });
                } catch (e) {
                    console.error('TradingView widget error:', e);
                    const wrap = el.querySelector('.tv-chart-wrap');
                    if (wrap) wrap.innerHTML = '<div style="color:#888;text-align:center;padding:40px;">차트 로드 실패 (종목 미지원)</div>';
                }
            };

            // 차트가 viewport 안에 있으면 즉시, 아니면 들어올 때 로드
            if ('IntersectionObserver' in window) {
                const obs = new IntersectionObserver((entries, observer) => {
                    entries.forEach(entry => {
                        if (entry.isIntersecting) {
                            observer.disconnect();
                            setTimeout(loadWidget, 50);
                        }
                    });
                }, { rootMargin: '200px' });   // 200px 위에서 미리 로드 시작
                obs.observe(el);
            } else {
                setTimeout(loadWidget, 80);   // 구형 브라우저 fallback
            }
        }

        function renderMarketBanner(m) {
            const el = document.getElementById('marketBanner');
            if (!m || !m.available) { el.innerHTML = ''; return; }
            const cls = m.passed_canslim_m ? 'mb-up' : (m.direction.includes('하락') || m.direction.includes('조정')) ? 'mb-down' : 'mb-flat';
            el.innerHTML = `
                <div class="market-banner">
                    <div class="mb-left">
                        <div class="mb-dot ${cls}"></div>
                        <div>
                            <div class="mb-label">${m.benchmark_name}: ${m.direction}</div>
                            <div class="mb-sub">${m.recommend}</div>
                        </div>
                    </div>
                    <div class="mb-right">
                        MA50 ${m.ma50_pct >= 0 ? '+' : ''}${m.ma50_pct}%<br>
                        MA200 ${m.ma200_pct >= 0 ? '+' : ''}${m.ma200_pct}%
                    </div>
                </div>`;
        }

        function renderVerdict(v) {
            const el = document.getElementById('verdictCard');
            if (!v) { el.innerHTML = ''; return; }
            const cls = v.color === 'green' ? 'verdict-green' : v.color === 'red' ? 'verdict-red' : 'verdict-yellow';
            const badgeCls = v.color === 'green' ? 'vb-green' : v.color === 'red' ? 'vb-red' : 'vb-yellow';
            const reasonsHTML = v.reasons.length ? `<ul class="verdict-reasons">${v.reasons.map(r => `<li>• ${r}</li>`).join('')}</ul>` : '';
            const warnsHTML = v.warnings && v.warnings.length ? `<div class="verdict-warnings">⚠ ${v.warnings.join(' · ')}</div>` : '';
            el.innerHTML = `
                <div class="verdict-card ${cls}">
                    <div class="verdict-badge ${badgeCls}">${v.decision}</div>
                    <div class="verdict-content">${reasonsHTML}${warnsHTML}</div>
                </div>`;
        }

        function renderDataWarnings(warnings) {
            const el = document.getElementById('dataWarnings');
            if (!warnings || warnings.length === 0) { el.innerHTML = ''; return; }
            el.innerHTML = `<div class="data-warning">⚠ 일부 데이터 누락: ${warnings.join(', ')}</div>`;
        }

        function renderFairValue(fv) {
            const el = document.getElementById('fvCard');
            if (!fv || !fv.available) {
                if (fv && fv.quality_class) {
                    const qc = fv.quality_class;
                    el.innerHTML = `<div class="fv-card"><div class="section-title" style="margin-top:0;">적정주가 추정 불가</div><div style="padding:12px;color:#ff9800;">카테고리: ${qc.label}<br><small style="color:#aaa;">${qc.note}</small></div></div>`;
                } else { el.innerHTML = ''; }
                return;
            }
            let cls = 'fv-fair';
            if (fv.upside_pct >= 10) cls = 'fv-up';
            else if (fv.upside_pct <= -10) cls = 'fv-down';
            const fmtUp = (p) => p == null ? '' : `<span style="color:${p>=0?'#4caf50':'#f44336'};font-size:0.72rem;">(${p>=0?'+':''}${p}%)</span>`;
            const sym = fv.currency === 'KRW' ? '₩' : '$';
            const fmtPrice = (v) => {
                if (v == null) return '';
                if (fv.currency === 'KRW') return '₩' + Math.round(v).toLocaleString();
                return '$' + v;
            };
            // 제외 사유 매핑 (excluded_methods에서 method별 reason 추출)
            const exclByMethod = {};
            (fv.excluded_methods || []).forEach(e => {
                const k = ({DCF:'dcf', PER:'per_based', Graham:'graham_number', '애널리스트':'analyst_target', 'P/S':'ps_based'})[e.method] || e.method;
                exclByMethod[k] = e.reason;
            });
            // 제외 표시 — "제외" 옆에 사유 작은 글씨 인라인 표시
            const exclTag = (key) => {
                const r = exclByMethod[key];
                if (!r) return '<span style="color:#666;">제외</span>';
                return `<div style="line-height:1.3;"><span style="color:#ff9800;font-weight:600;">❌ 제외</span><div style="font-size:0.65rem;color:#999;margin-top:2px;font-weight:400;">${r}</div></div>`;
            };
            const dcfStr = fv.dcf ? `${fmtPrice(fv.dcf.fair_value)} ${fmtUp(fv.dcf.upside_pct)}` : exclTag('dcf');
            const perStr = fv.per_based ? `${fmtPrice(fv.per_based.fair_value)} ${fmtUp(fv.per_based.upside_pct)}` : exclTag('per_based');
            const grahamStr = fv.graham_number ? `${fmtPrice(fv.graham_number)}` : exclTag('graham_number');
            const analystStr = fv.analyst_target ? `${fmtPrice(fv.analyst_target.fair_value)} ${fmtUp(fv.analyst_target.upside_pct)}` : '<span style="color:#666;">—</span>';
            const psStr = fv.ps_based ? `${fmtPrice(fv.ps_based.fair_value)} ${fmtUp(fv.ps_based.upside_pct)}` : null;

            const weights = fv.weights_used || {};
            const weightLabels = {dcf: 'DCF', per_based: 'PER', graham_number: 'Graham', analyst_target: '애널', ps_based: 'P/S'};
            const weightText = Object.keys(weights).length
                ? Object.entries(weights).map(([k, w]) => `${weightLabels[k]||k} ${Math.round(w*100)}%`).join(' · ')
                : '';

            const qc = fv.quality_class || {};
            const confCol = qc.confidence === 'high' ? '#4caf50' : qc.confidence === 'medium' ? '#ffeb3b' : '#f44336';
            const confLabel = qc.confidence === 'high' ? '신뢰도 높음' : qc.confidence === 'medium' ? '신뢰도 보통' : '신뢰도 낮음';
            const catBadge = qc.label
                ? `<div style="display:inline-block;padding:3px 10px;border-radius:12px;background:${confCol}22;color:${confCol};font-size:0.72rem;font-weight:600;margin-left:8px;">${qc.label} · ${confLabel}</div>`
                : '';
            const warningsHTML = qc.warnings && qc.warnings.length
                ? `<div style="background:#2a2410;border-left:3px solid #ff9800;padding:8px 12px;margin-top:10px;border-radius:6px;font-size:0.75rem;color:#ffb74d;">${qc.warnings.map(w=>`⚠ ${w}`).join('<br>')}</div>`
                : '';

            // 카테고리 + 제외 평가법 안내 박스 — 사용자가 즉시 이해할 수 있게 명시
            let methodPolicyHTML = '';
            if (qc.label || (fv.excluded_methods && fv.excluded_methods.length)) {
                const usedNames = Object.keys(fv.weights_used || {}).map(k => ({dcf:'DCF',per_based:'PER',graham_number:'Graham',analyst_target:'애널리스트',ps_based:'P/S'})[k]||k);
                const exclList = (fv.excluded_methods || []).map(e => `<li><b>${e.method}</b> — ${e.reason}</li>`).join('');
                const wr = fv.weights_rationale || {};
                const basisHTML = wr.category_basis
                    ? `<div style="font-size:0.72rem;color:#9aa6c9;margin-bottom:6px;">🧭 분류 근거: ${wr.category_basis}</div>`
                    : '';
                const explainHTML = wr.explanation
                    ? `<div style="background:rgba(255,255,255,0.04);border-left:3px solid ${confCol};padding:8px 10px;margin-top:8px;border-radius:6px;font-size:0.74rem;color:#cdd2dd;line-height:1.55;">💡 <b>왜 이 가중치인가?</b><br>${wr.explanation}</div>`
                    : '';
                methodPolicyHTML = `
                    <div style="background:rgba(13,95,217,0.08);border:1px solid rgba(13,95,217,0.3);border-radius:10px;padding:12px 14px;margin-top:10px;font-size:0.78rem;">
                        <div style="color:${confCol};font-weight:700;margin-bottom:4px;">📋 ${qc.label || '표준 평가'}</div>
                        ${qc.note ? `<div style="color:#bbb;margin-bottom:6px;">${qc.note}</div>` : ''}
                        ${basisHTML}
                        ${usedNames.length ? `<div style="color:#aaa;font-size:0.74rem;">✅ 적용된 평가법: <b style="color:#ddd;">${usedNames.join(' · ')}</b></div>` : ''}
                        ${explainHTML}
                        ${exclList ? `<details style="margin-top:6px;"><summary style="cursor:pointer;color:#ff9800;font-size:0.74rem;">❌ 제외된 평가법 ${fv.excluded_methods.length}개 보기</summary><ul style="padding-left:18px;margin-top:4px;color:#999;font-size:0.72rem;">${exclList}</ul></details>` : ''}
                    </div>`;
            }
            const noteHTML = '';  // methodPolicyHTML로 통합됨
            const excludedHTML = '';  // methodPolicyHTML로 통합됨

            // WACC 산출 내역 (회계사 자문 반영)
            let waccHTML = '';
            if (fv.dcf && fv.dcf.assumptions && fv.dcf.assumptions.wacc_breakdown) {
                const wb = fv.dcf.assumptions.wacc_breakdown;
                const tg = (fv.dcf.assumptions.terminal_growth * 100).toFixed(1);
                const wacc = (wb.wacc * 100).toFixed(2);
                const re = (wb.cost_of_equity * 100).toFixed(2);
                const rd = (wb.cost_of_debt * 100).toFixed(2);
                const we = (wb.weight_equity * 100).toFixed(0);
                const wd = (wb.weight_debt * 100).toFixed(0);
                waccHTML = `<details style="margin-top:8px;font-size:0.72rem;color:#888;">
                    <summary style="cursor:pointer;">DCF 할인율 ${wacc}% 산출 내역 (${tt('WACC')})</summary>
                    <div style="padding:8px 12px;margin-top:4px;background:#0f0f1a;border-radius:6px;line-height:1.7;">
                        ${tt('WACC')} = (자기자본비중 × ${tt('CAPM')} 자본비용) + (부채비중 × 차입이자율 × (1−법인세))<br>
                        • 자본비용 ${re}% = 무위험률 ${(wb.rf*100).toFixed(1)}% + 베타 ${wb.beta} × 시장프리미엄 5.5%<br>
                        • 차입이자율 ${rd}% (재무제표 추정 또는 BBB급 스프레드)<br>
                        • 자본구조: 자기자본 ${we}% / 부채 ${wd}%<br>
                        • 영구성장률 ${tg}% (인플레 이하 보수 가정)
                    </div>
                </details>`;
            }

            const extraPSRow = psStr ? `<div class="fv-box"><div class="fv-box-label">${tt('P/S')} 기반 (매출 배수)</div><div class="fv-box-value">${psStr}</div></div>` : '';

            const fvNow = new Date().toLocaleString('ko-KR', {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'});
            const dm = window._latestDataMeta || {};
            const finBasis = dm.financialEndDate ? `📊 재무 ${dm.financialEndDate} (${dm.financialPeriodType||''})` : '📅 연간 결산';
            const sourceTag = dm.financialSourceShort ? ` · 🏛 ${dm.financialSourceShort}` : '';
            el.innerHTML = `
                <div class="fv-card">
                    <div class="section-title" style="margin-top:0;">적정주가 추정 <span style="font-size:0.7rem;font-weight:400;color:#888;">(${fv.sector || '?'} 섹터)</span>${catBadge}</div>
                    <div style="font-size:0.7rem;color:#777;margin-bottom:10px;line-height:1.5;">${finBasis} + 현재가 기준${sourceTag} · 분석 시점 ${fvNow}</div>
                    <div class="fv-grid">
                        <div class="fv-box"><div class="fv-box-label">현재가</div><div class="fv-box-value">${fmtPrice(fv.current_price)}</div></div>
                        <div class="fv-box"><div class="fv-box-label">종합 적정가</div><div class="fv-box-value">${fmtPrice(fv.composite_fair_value)}</div><div class="fv-box-sub">${fv.upside_pct >= 0 ? '+' : ''}${fv.upside_pct}%</div></div>
                        <div class="fv-box"><div class="fv-box-label">${tt('DCF')} ${fv.dcf ? `(성장률 ${(fv.dcf.assumptions.growth_5y*100).toFixed(0)}%)` : ''}</div><div class="fv-box-value">${dcfStr}</div></div>
                        <div class="fv-box"><div class="fv-box-label">${tt('PER')} 기반 ${fv.per_based ? `(PE ${fv.per_based.assumption_pe})` : ''}</div><div class="fv-box-value">${perStr}</div></div>
                        <div class="fv-box"><div class="fv-box-label">애널리스트${fv.analyst_target && fv.analyst_target.num_analysts ? ` (${fv.analyst_target.num_analysts}명)` : ''}</div><div class="fv-box-value">${analystStr}</div></div>
                        <div class="fv-box"><div class="fv-box-label">${tt('Graham')} <span style="font-size:0.66rem;color:#666;">(√(22.5×EPS×BPS))</span></div><div class="fv-box-value">${grahamStr}</div></div>
                        ${extraPSRow}
                    </div>
                    ${weightText ? `<div style="text-align:center;font-size:0.72rem;color:#666;margin-top:8px;">가중치: ${weightText}</div>` : ''}
                    ${methodPolicyHTML}
                    ${warningsHTML}
                    ${noteHTML}
                    <div class="fv-verdict ${cls}">${fv.verdict}</div>
                    ${waccHTML}
                    ${excludedHTML}
                </div>`;
        }

        function renderRSRating(rs) {
            const el = document.getElementById('rsCard');
            if (!rs || !rs.available) { el.innerHTML = ''; return; }
            const periods = [
                {key: 'rs_1m', label: '1M'},
                {key: 'rs_3m', label: '3M'},
                {key: 'rs_6m', label: '6M'},
                {key: 'rs_12m', label: '12M'},
            ];
            const compColor = rs.rs_composite >= 80 ? '#4caf50' : rs.rs_composite >= 60 ? '#8bc34a' : rs.rs_composite >= 40 ? '#ffeb3b' : '#f44336';
            const bars = periods.map(p => {
                const v = rs[p.key];
                if (v == null) return `<div class="rs-bar-item"><div class="rs-bar-period">${p.label}</div><div class="rs-bar-track"></div><div class="rs-bar-val">—</div></div>`;
                const col = v >= 80 ? '#4caf50' : v >= 60 ? '#8bc34a' : v >= 40 ? '#ffeb3b' : '#f44336';
                return `<div class="rs-bar-item"><div class="rs-bar-period">${p.label}</div><div class="rs-bar-track"><div class="rs-bar-fill" style="width:${v}%;background:${col};"></div></div><div class="rs-bar-val" style="color:${col};">${v}</div></div>`;
            }).join('');
            el.innerHTML = `
                <div class="rs-card">
                    <div class="rs-header">
                        <div class="rs-title">${tt('RS')} Rating (${rs.benchmark} 대비)</div>
                        <div><span class="rs-composite" style="color:${compColor};">${rs.rs_composite ?? '—'}</span><span class="rs-label">${rs.label}</span></div>
                    </div>
                    <div class="rs-bars">${bars}</div>
                </div>`;
        }

        function renderFearGreed(fg) {
            if (!fg || fg.score === null) { document.getElementById('fgCard').innerHTML = `<div style="color:#888;padding:40px;">공포/탐욕 지수 데이터 부족</div>`; return; }
            const angle = (fg.score / 100) * 180 - 90;
            const color = getFgColor(fg.score);
            let indHTML = '';
            fg.indicators.forEach(ind => {
                indHTML += `<div class="fg-ind-item">
                    <div class="fg-ind-name">${ind.name}</div>
                    <div class="fg-ind-value">${ind.value}</div>
                    <div class="fg-ind-bar-wrap"><div class="fg-ind-bar" style="width:${ind.score}%;background:${getBarColor(ind.score)};"></div></div>
                    <div class="fg-ind-label">${ind.label}</div>
                </div>`;
            });
            document.getElementById('fgCard').innerHTML = `
                <div style="text-align:center;color:#888;font-size:0.85rem;margin-bottom:14px;line-height:1.55;">
                    투자자 심리를 0~100으로 표시합니다.<br>
                    <strong style="color:#f44336;">낮을수록 공포</strong> (매도 과열, 저가매수 기회) ·
                    <strong style="color:#4caf50;">높을수록 탐욕</strong> (매수 과열, 고점 주의)
                </div>
                <div class="fg-gauge-wrap"><div class="fg-gauge-bg"></div><div class="fg-needle" id="fgNeedle" style="transform:rotate(-90deg);"></div></div>
                <div class="fg-scale"><span>극단적 공포 (0)</span><span>중립 (50)</span><span>극단적 탐욕 (100)</span></div>
                <div class="fg-score" style="color:${color}">${fg.score}</div>
                <div class="fg-label" style="color:${color}">${fg.label}</div>
                <div style="text-align:center;color:#666;font-size:0.75rem;margin:4px 0 16px;">※ 워렌 버핏: "남들이 탐욕스러울 때 두려워하고, 남들이 두려워할 때 탐욕스러워져라"</div>
                <div class="fg-indicators">${indHTML}</div>`;
            setTimeout(() => { const n = document.getElementById('fgNeedle'); if (n) n.style.transform = `rotate(${angle}deg)`; }, 100);
        }

        function renderPositions(pos) {
            if (!pos) return;
            let sentBg, sentColor;
            if (pos.sentiment.includes('약세')) { sentBg = '#2a1a1a'; sentColor = '#f44336'; }
            else if (pos.sentiment.includes('강세')) { sentBg = '#0a2a0a'; sentColor = '#4caf50'; }
            else { sentBg = '#2a2a1a'; sentColor = '#ffeb3b'; }
            if (pos.short.length === 0 && pos.long.length === 0) { document.getElementById('posCard').innerHTML = `<div style="color:#888;padding:40px;text-align:center;">포지션 데이터가 없습니다.</div>`; return; }
            let html = `<div class="pos-sentiment" style="background:${sentBg}"><div class="pos-sentiment-label" style="color:${sentColor}">${pos.sentiment}</div><div class="pos-sentiment-detail">${pos.sentimentDetail}</div></div>`;
            if (pos.short.length > 0) { html += `<div class="pos-section-title">공매도 (Short)</div>`; pos.short.forEach(s => { html += `<div class="pos-item"><span class="pos-item-name">${s.name}</span><span class="pos-item-value">${s.value}</span></div>`; }); }
            if (pos.long.length > 0) { html += `<div class="pos-section-title">보유 현황 (Long)</div>`; pos.long.forEach(l => { html += `<div class="pos-item"><span class="pos-item-name">${l.name}</span><span class="pos-item-value">${l.value}</span></div>`; }); }
            document.getElementById('posCard').innerHTML = html;
        }

        function renderOptions(opt) {
            if (!opt || !opt.available) { document.getElementById('optCard').innerHTML = `<div style="color:#888;padding:40px;text-align:center;">옵션 데이터가 없습니다. (한국 주식은 옵션 데이터 미제공)</div>`; return; }
            const pcrColor = opt.pcrOI >= 1.0 ? '#f44336' : opt.pcrOI >= 0.7 ? '#ffeb3b' : '#4caf50';
            let html = `
                <div style="text-align:center;color:#888;font-size:0.8rem;margin-bottom:16px;">만기일: ${opt.expDate} | 현재가: $${opt.currentPrice}</div>
                <div class="opt-summary">
                    <div class="opt-box">
                        <div class="opt-box-label">Put/Call 비율 (미결제약정)</div>
                        <div class="opt-box-value" style="color:${pcrColor}">${opt.pcrOI ?? 'N/A'}</div>
                        <div style="font-size:0.75rem;color:#888;margin-top:4px;">${opt.pcrLabel}</div>
                    </div>
                    <div class="opt-box">
                        <div class="opt-box-label">거래량 비교</div>
                        <div style="font-size:0.85rem;margin-top:8px;"><span style="color:#4caf50;">콜 ${opt.totalCallVol.toLocaleString()}</span> / <span style="color:#f44336;">풋 ${opt.totalPutVol.toLocaleString()}</span></div>
                        <div style="font-size:0.85rem;margin-top:4px;"><span style="color:#4caf50;">콜OI ${opt.totalCallOI.toLocaleString()}</span> / <span style="color:#f44336;">풋OI ${opt.totalPutOI.toLocaleString()}</span></div>
                    </div>
                </div>
                <div class="opt-maxpain"><div class="opt-maxpain-label">Max Pain (옵션 만기 시 예상 수렴 가격)</div><div class="opt-maxpain-value">$${opt.maxPain}</div><div class="opt-maxpain-desc">${opt.maxPainDesc}</div></div>`;
            if (opt.putOITop.length > 0) {
                const maxOI = Math.max(...opt.putOITop.map(p => p.oi));
                html += `<div class="pos-section-title">풋옵션 미결제약정 TOP</div>`;
                opt.putOITop.forEach(p => {
                    const pct = (p.oi / maxOI * 100);
                    html += `<div class="opt-strike-item"><div class="opt-strike-price" style="color:#f44336;">$${p.strike}</div><div class="opt-strike-bar-wrap"><div class="opt-strike-bar" style="width:${pct}%;background:#f44336;"></div></div><div class="opt-strike-oi">${p.oi.toLocaleString()}</div><div class="opt-strike-desc">${p.desc}</div></div>`;
                });
            }
            if (opt.callOITop.length > 0) {
                const maxOI = Math.max(...opt.callOITop.map(c => c.oi));
                html += `<div class="pos-section-title" style="margin-top:20px;">콜옵션 미결제약정 TOP</div>`;
                opt.callOITop.forEach(c => {
                    const pct = (c.oi / maxOI * 100);
                    html += `<div class="opt-strike-item"><div class="opt-strike-price" style="color:#4caf50;">$${c.strike}</div><div class="opt-strike-bar-wrap"><div class="opt-strike-bar" style="width:${pct}%;background:#4caf50;"></div></div><div class="opt-strike-oi">${c.oi.toLocaleString()}</div><div class="opt-strike-desc">${c.desc}</div></div>`;
                });
            }
            html += `<div style="margin-top:20px;padding:16px;background:#0f0f1a;border-radius:12px;font-size:0.8rem;color:#888;line-height:1.8;"><strong style="color:#aaa;">읽는 법</strong><br><span style="color:#f44336;">풋옵션</span>: 해당 가격 아래로 떨어질 것이라는 베팅<br><span style="color:#4caf50;">콜옵션</span>: 해당 가격 위로 올라갈 것이라는 베팅<br><span style="color:#7b2ff7;">Max Pain</span>: 옵션 만기일 수렴 예상 가격<br><strong>P/C > 1.0</strong>: 하락 베팅 우세 | <strong>< 0.7</strong>: 상승 베팅 우세</div>`;
            document.getElementById('optCard').innerHTML = html;
        }

        function renderOverall(o) {
            if (!o) return;
            document.getElementById('overallCard').innerHTML = `<div class="grade-circle grade-${o.grade}">${o.grade}</div><div class="overall-text">${o.gradeText} (${o.rate}%)</div><div class="overall-detail">${o.yes}/${o.total} 기준 통과</div>`;
        }

        function renderInvestors(investors, dataMeta) {
            const icons = { buffett: 'B', graham: 'G', lynch: 'L', oneil: 'O', fisher: 'F' };
            const meta = dataMeta || {};
            const metaLine = (meta.financialEndDate)
                ? `<div style="padding:4px 20px 10px;font-size:0.7rem;color:#777;line-height:1.4;">📊 재무 ${meta.financialEndDate} (${meta.financialPeriodType||''}) · 출처 ${meta.financialSourceShort||''}</div>`
                : '';
            let html = '';
            investors.forEach((inv, i) => {
                const rc = inv.rate >= 70 ? 'rate-high' : inv.rate >= 40 ? 'rate-mid' : 'rate-low';
                const pc = inv.rate >= 70 ? '#4caf50' : inv.rate >= 40 ? '#ffeb3b' : '#f44336';
                let cHTML = '';
                inv.criteria.forEach(c => {
                    let bc, bt;
                    if (c.passed === true) { bc = 'badge-yes'; bt = 'YES'; }
                    else if (c.passed === false) { bc = 'badge-no'; bt = 'NO'; }
                    else { bc = 'badge-na'; bt = 'N/A'; }
                    const nameHTML = window.StockIntoTooltip ? window.StockIntoTooltip.markup(c.name) : c.name;
                    cHTML += `<div class="criteria-item"><div class="criteria-name">${nameHTML}</div><div class="criteria-value">${c.value}</div><div class="badge ${bc}">${bt}</div></div>`;
                });

                // 버핏 전용: 엄격 등급 배지
                let strictBadge = '';
                if (inv.strict_grade) {
                    const sg = inv.strict_grade;
                    const colorMap = { green: '#4caf50', yellow: '#ffeb3b', red: '#f44336', gray: '#888' };
                    const bg = sg.color === 'green' ? 'rgba(76,175,80,0.15)'
                            : sg.color === 'yellow' ? 'rgba(255,235,59,0.15)'
                            : sg.color === 'red' ? 'rgba(244,67,54,0.15)'
                            : 'rgba(136,136,136,0.15)';
                    const col = colorMap[sg.color] || '#888';
                    strictBadge = `<div style="margin-top:10px;padding:10px 14px;background:${bg};border-left:3px solid ${col};border-radius:8px;font-size:0.82rem;">
                        <strong style="color:${col};font-size:1rem;">엄격 등급: ${sg.grade}</strong>
                        <div style="color:#ccc;margin-top:2px;">${sg.text}</div>
                    </div>`;
                }

                // 린치 전용: 6 카테고리 자동 분류 표시
                let categoryBadge = '';
                if (inv.category) {
                    const cat = inv.category;
                    const catColorMap = {
                        'FAST_GROWER':  '#4caf50',
                        'STALWART':     '#3B82F6',
                        'SLOW_GROWER':  '#888',
                        'ASSET_PLAY':   '#a78bfa',
                        'TURNAROUND':   '#f59e0b',
                        'CYCLICAL':     '#ec4899',
                        'UNCLASSIFIED': '#666',
                    };
                    const catCol = catColorMap[cat.code] || '#888';
                    categoryBadge = `<div style="margin-top:10px;padding:10px 14px;background:rgba(59,130,246,0.08);border-left:3px solid ${catCol};border-radius:8px;font-size:0.82rem;">
                        <strong style="color:${catCol};font-size:0.95rem;">📂 카테고리: ${cat.label}</strong>
                        <div style="color:#aaa;margin-top:3px;font-size:0.78rem;">${cat.desc}</div>
                    </div>`;
                }
                // 통합: 버핏 strictBadge 또는 린치 categoryBadge
                const extraBadge = strictBadge || categoryBadge;

                html += `
                    <div class="investor-card">
                        <div class="investor-header" data-action="toggleCard" data-card-idx="${i}">
                            <div class="investor-left">
                                <div class="investor-icon icon-${inv.icon}">${icons[inv.icon]}</div>
                                <div><div class="investor-name">${inv.label || inv.name + '이라면?'}</div><div class="investor-sub">${tt(inv.sub)}</div></div>
                            </div>
                            <div class="investor-right">
                                <span class="pass-rate ${rc}">${inv.yes}/${inv.total} (${inv.rate}%)</span>
                                <span class="arrow" id="arrow-${i}">&#9660;</span>
                            </div>
                        </div>
                        <div class="progress-bar"><div class="progress-fill" style="width:${inv.rate}%;background:${pc};"></div></div>
                        <div class="criteria-list" id="criteria-${i}">${metaLine}${cHTML}${extraBadge ? '<div style="padding:0 20px 14px;">' + extraBadge + '</div>' : ''}</div>
                    </div>`;
            });
            document.getElementById('investorCards').innerHTML = html;
        }

        function toggleCard(i) { document.getElementById(`criteria-${i}`).classList.toggle('open'); document.getElementById(`arrow-${i}`).classList.toggle('open'); }

        function renderQuality(q) {
            const el = document.getElementById('qualityCard');
            if (!q || !q.available) { el.innerHTML = ''; return; }
            const qs = q.quality_score ?? 0;
            const col = qs >= 70 ? '#4caf50' : qs >= 50 ? '#ffeb3b' : '#f44336';
            const strengthsHTML = q.strengths && q.strengths.length ? `<div class="quality-section qs-strength"><h4>✓ 강점</h4><ul>${q.strengths.map(s => `<li>${s}</li>`).join('')}</ul></div>` : '';
            const flagsHTML = q.flags && q.flags.length ? `<div class="quality-section qs-flag"><h4>⚠ 위험신호</h4><ul>${q.flags.map(f => `<li>${f}</li>`).join('')}</ul></div>` : '';
            const metrics = [
                {label: 'FCF / 순이익', v: q.fcf_ni_ratio},
                {label: '발생액 비율', v: q.accruals_ratio},
                {label: '매출채권 - 매출 증가율', v: q.ar_growth_vs_rev},
                {label: '재고 - 매출 증가율', v: q.inventory_growth_vs_rev},
            ].filter(m => m.v !== null && m.v !== undefined);
            const metricsHTML = metrics.length ? `<div class="quality-metrics">${metrics.map(m => `<div class="quality-metric"><div class="qm-label">${tt(m.label)}</div><div class="qm-value">${m.v}</div></div>`).join('')}</div>` : '';
            el.innerHTML = `
                <div class="quality-card">
                    <div class="section-title" style="margin-top:0;">재무 품질 (Earnings Quality)</div>
                    <div class="quality-score-wrap">
                        <div class="quality-score-val" style="color:${col};">${qs}<span style="font-size:1rem;color:#666;">/100</span></div>
                        <div class="quality-bar-track"><div class="quality-bar-fill" style="width:${qs}%;background:${col};"></div></div>
                        <div class="quality-score-label">품질 점수</div>
                    </div>
                    ${strengthsHTML}${flagsHTML}${metricsHTML}
                </div>`;
        }

        function renderTrendCharts(h, currency) {
            const el = document.getElementById('trendCharts');
            if (!h || !h.available) { el.innerHTML = `<div style="color:#888;padding:40px;text-align:center;">재무제표 추이 데이터가 부족합니다.</div>`; return; }
            const isKR = currency === 'KRW';
            const bc = h.roe_consistency || {};
            const yearsRange = (h.years && h.years.length) ? `${h.years[0]}~${h.years[h.years.length-1]} 결산 기준` : '연간 결산 기준';
            const cagrHTML = `
                <div style="font-size:0.72rem;color:#888;margin-bottom:8px;text-align:center;">📅 ${yearsRange} · 출처: ${isKR ? 'DART 공시' : 'SEC EDGAR'}</div>
                <div class="cagr-row">
                    ${h.revenue_cagr != null ? `<div class="cagr-pill">매출 ${tt('CAGR')} <b>${(h.revenue_cagr*100).toFixed(1)}%</b></div>` : ''}
                    ${h.eps_cagr != null ? `<div class="cagr-pill">${tt('EPS')} ${tt('CAGR')} <b>${(h.eps_cagr*100).toFixed(1)}%</b></div>` : ''}
                    ${bc.passed_buffett_10yr_proxy ? `<div class="cagr-pill" style="color:#4caf50;">✓ ${tt('ROE')} 꾸준히 15%+ (${bc.years_above_15pct}/${bc.total_measured}년)</div>` : bc.total_measured ? `<div class="cagr-pill">${tt('ROE')} 15%+ ${bc.years_above_15pct}/${bc.total_measured}년</div>` : ''}
                </div>`;
            el.innerHTML = `
                <div class="chart-card"><div class="chart-title">매출 (Revenue)</div><div class="chart-canvas-wrap"><canvas id="chRevenue"></canvas></div></div>
                <div class="chart-card"><div class="chart-title">순이익 (Net Income)</div><div class="chart-canvas-wrap"><canvas id="chNetIncome"></canvas></div></div>
                <div class="chart-card"><div class="chart-title">${tt('EPS')} (주당순이익)</div><div class="chart-canvas-wrap"><canvas id="chEPS"></canvas></div></div>
                <div class="chart-card"><div class="chart-title">${tt('ROE')} (%)</div><div class="chart-canvas-wrap"><canvas id="chROE"></canvas></div></div>
                <div class="chart-card"><div class="chart-title">${tt('FCF')} (Free Cash Flow)</div><div class="chart-canvas-wrap"><canvas id="chFCF"></canvas></div></div>
                ${cagrHTML}`;
            // 원화: /1e12 (조원), USD: /1e6 (백만$)
            const scale = isKR ? 1e12 : 1e6;
            const bigUnit = isKR ? '조원' : '백만 $';
            const epsUnit = isKR ? '원' : '$';
            const scaleArr = arr => arr.map(v => v == null ? null : v / scale);
            const toPct = arr => arr.map(v => v == null ? null : v * 100);
            makeBarChart('chRevenue', h.years, scaleArr(h.revenue), '#7b2ff7', bigUnit, '매출');
            makeBarChart('chNetIncome', h.years, scaleArr(h.net_income), '#00d2ff', bigUnit, '순이익');
            makeLineChart('chEPS', h.years, h.eps, '#4caf50', epsUnit, 'EPS');
            makeLineChart('chROE', h.years, toPct(h.roe), '#ff9800', '%', 'ROE');
            makeBarChart('chFCF', h.years, scaleArr(h.fcf), '#8bc34a', bigUnit, 'FCF');
        }

        // 한국 주식 KRX 수급 (외국인 보유율 + 투자자별 매매 + 공매도 잔고)
        function renderKRX(krx, isKR) {
            const tabBtn = document.getElementById('tabbtn-krx');
            const card = document.getElementById('krxCard');
            // 미국 종목이면 탭 숨김
            if (!isKR) {
                if (tabBtn) tabBtn.style.display = 'none';
                if (card) card.innerHTML = '';
                return;
            }
            // 한국 종목이면 탭은 항상 표시
            if (tabBtn) tabBtn.style.display = '';
            // lazy 플래그면 placeholder
            if (krx && krx.lazy) {
                if (card) card.innerHTML = `<div style="color:#888;padding:40px;text-align:center;">🇰🇷 수급 탭을 클릭하면 데이터를 불러옵니다.</div>`;
                return;
            }
            // 데이터 없거나 실패 응답 — 탭은 유지, 카드에 에러/재시도 표시
            if (!krx || !krx.available) {
                const errMsg = (krx && krx.error) ? krx.error : 'KRX 데이터를 받지 못했습니다.';
                if (card) card.innerHTML = `
                    <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:14px;padding:24px;text-align:center;">
                        <div style="font-size:1.4rem;margin-bottom:10px;">😅</div>
                        <div style="color:#ddd;margin-bottom:12px;font-weight:600;">${errMsg}</div>
                        <div style="color:#888;font-size:0.82rem;margin-bottom:18px;">한국거래소 응답이 지연되거나 일시적으로 막혔을 수 있습니다.</div>
                        <button data-action="retryKrx" style="padding:10px 18px;min-height:44px;border-radius:9999px;border:1px solid var(--border);background:transparent;color:var(--accent-cyan);cursor:pointer;font-size:0.85rem;font-weight:600;font-family:inherit;">🔄 다시 시도</button>
                    </div>`;
                return;
            }

            // 금액 포맷터: 억원 단위 (절대값 1조 이상이면 조원)
            function fmtKRW(v) {
                if (v == null) return '—';
                const abs = Math.abs(v);
                const sign = v >= 0 ? '+' : '−';
                if (abs >= 1e12) return `${sign}${(abs/1e12).toFixed(2)}조원`;
                if (abs >= 1e8)  return `${sign}${(abs/1e8).toFixed(0)}억원`;
                return `${sign}${(abs/1e4).toFixed(0)}만원`;
            }
            function fmtKRWNoSign(v) {
                if (v == null) return '—';
                const abs = Math.abs(v);
                if (abs >= 1e12) return `${(abs/1e12).toFixed(2)}조원`;
                if (abs >= 1e8)  return `${(abs/1e8).toFixed(0)}억원`;
                return `${(abs/1e4).toFixed(0)}만원`;
            }
            function colorOf(v) {
                if (v == null || v === 0) return '#888';
                return v > 0 ? '#4caf50' : '#f44336';
            }

            // ── 외국인 보유율 카드
            let foreignHTML = '';
            if (krx.foreign && krx.foreign.available) {
                const f = krx.foreign;
                const dCol5 = colorOf(f.delta_5d_pct);
                const dCol20 = colorOf(f.delta_20d_pct);
                const limitCol = f.limit_exhaustion_pct >= 90 ? '#ff9800' : '#888';
                foreignHTML = `
                <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:14px;padding:18px;margin-bottom:14px;">
                    <div style="font-size:0.78rem;color:#888;margin-bottom:6px;">${tt('외국인 보유율')} <span style="font-size:0.7rem;color:#666;">(${f.latest_date} 기준)</span></div>
                    <div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;">
                        <div style="font-size:2rem;font-weight:700;color:var(--accent-cyan);">${f.latest_pct.toFixed(2)}%</div>
                        <div style="font-size:0.82rem;color:${limitCol};">한도 소진률 ${f.limit_exhaustion_pct.toFixed(1)}%</div>
                    </div>
                    <div style="display:flex;gap:18px;margin-top:10px;font-size:0.8rem;flex-wrap:wrap;">
                        <span>5일 변화 <b style="color:${dCol5};">${f.delta_5d_pct == null ? '—' : (f.delta_5d_pct > 0 ? '+' : '') + f.delta_5d_pct + '%p'}</b></span>
                        <span>20일 변화 <b style="color:${dCol20};">${f.delta_20d_pct == null ? '—' : (f.delta_20d_pct > 0 ? '+' : '') + f.delta_20d_pct + '%p'}</b></span>
                    </div>
                    <div style="font-size:0.7rem;color:#666;margin-top:8px;">
                        보유 ${(f.shares_held/1e6).toFixed(1)}백만주 / 상장 ${(f.shares_listed/1e6).toFixed(1)}백만주
                    </div>
                </div>`;
            }

            // ── 투자자별 매매 카드
            let tradingHTML = '';
            if (krx.trading && krx.trading.available) {
                const t = krx.trading;
                const labels = {foreign: '외국인', institution: '기관', individual: '개인', pension: '연기금'};
                function rowHTML(period, agg) {
                    if (!agg) return '';
                    const items = ['foreign', 'institution', 'individual', 'pension'].map(k => {
                        const v = agg[k];
                        return `<div style="flex:1;min-width:120px;background:var(--bg-primary);padding:10px 12px;border-radius:10px;border-left:3px solid ${colorOf(v)};">
                            <div style="font-size:0.72rem;color:#888;margin-bottom:3px;">${labels[k]}</div>
                            <div style="font-size:0.92rem;font-weight:700;color:${colorOf(v)};">${fmtKRW(v)}</div>
                        </div>`;
                    }).join('');
                    return `
                    <div style="margin-bottom:12px;">
                        <div style="font-size:0.78rem;color:#aaa;margin-bottom:8px;">${period} 누적 순매수</div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">${items}</div>
                    </div>`;
                }
                tradingHTML = `
                <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:14px;padding:18px;margin-bottom:14px;">
                    <div style="font-size:0.78rem;color:#888;margin-bottom:12px;">투자자별 매매 동향 <span style="font-size:0.7rem;color:#666;">(${t.since_date} ~ ${t.until_date})</span></div>
                    ${rowHTML('최근 5거래일', t.by_5d)}
                    ${rowHTML('최근 20거래일', t.by_20d)}
                    <div style="font-size:0.7rem;color:#666;margin-top:6px;">+ 매수 우세 / − 매도 우세 — 외국인·기관 동반 매수면 신뢰도↑</div>
                </div>`;
            }

            // ── 공매도 잔고 카드
            let shortHTML = '';
            if (krx.short && krx.short.available) {
                const s = krx.short;
                const dCol = colorOf(-(s.delta_5d_balance || 0));  // 잔고 감소가 좋은 신호 → 양수 색
                const pctCol = s.latest_pct_of_listed >= 2 ? '#ff9800' : '#888';
                shortHTML = `
                <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:14px;padding:18px;margin-bottom:14px;">
                    <div style="font-size:0.78rem;color:#888;margin-bottom:6px;">${tt('공매도')} 잔고 <span style="font-size:0.7rem;color:#666;">(${s.latest_date} 기준)</span></div>
                    <div style="display:flex;gap:18px;flex-wrap:wrap;align-items:baseline;">
                        <div><div style="font-size:0.7rem;color:#666;">잔고 수량</div><div style="font-size:1.1rem;font-weight:700;">${(s.latest_balance/1e4).toFixed(0)}만 주</div></div>
                        <div><div style="font-size:0.7rem;color:#666;">잔고 평가액</div><div style="font-size:1.1rem;font-weight:700;">${fmtKRWNoSign(s.latest_balance_value)}</div></div>
                        <div><div style="font-size:0.7rem;color:#666;">상장 대비</div><div style="font-size:1.1rem;font-weight:700;color:${pctCol};">${s.latest_pct_of_listed.toFixed(2)}%</div></div>
                    </div>
                    <div style="margin-top:8px;font-size:0.78rem;">
                        5일 잔고 변화 <b style="color:${dCol};">${s.delta_5d_balance == null ? '—' : (s.delta_5d_balance > 0 ? '+' : '') + (s.delta_5d_balance/1e4).toFixed(0) + '만 주'}</b>
                        <span style="color:#666;margin-left:6px;">(증가=하락 베팅 강화 / 감소=청산)</span>
                    </div>
                </div>`;
            }

            const noteHTML = `<div style="font-size:0.7rem;color:#666;text-align:center;margin-top:8px;font-style:italic;">출처: 한국거래소(KRX) · 일별 공시값 · 24시간 캐시</div>`;
            card.innerHTML = `
                <div class="section-title" style="margin-top:0;">🇰🇷 한국 시장 수급</div>
                ${foreignHTML}${tradingHTML}${shortHTML}${noteHTML}`;
        }

        function fmtAxis(v, unit) {
            if (v == null) return '—';
            const abs = Math.abs(v);
            // 큰 수는 K/M 약어 (단, 단위가 %·원·$이면 그대로)
            if (unit === '%') return v.toFixed(1);
            if (abs >= 1e9) return (v/1e9).toFixed(1) + 'B';
            if (abs >= 1e6) return (v/1e6).toFixed(1) + 'M';
            if (abs >= 1e3) return (v/1e3).toFixed(1) + 'K';
            return v.toLocaleString(undefined, {maximumFractionDigits: 1});
        }

        function baseOpts(unit, label) {
            return {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { display: !!label, labels: { color: '#bbb', font: { size: 11 } } },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${label || '값'}: ${ctx.parsed.y != null ? ctx.parsed.y.toLocaleString(undefined, {maximumFractionDigits: 2}) : '—'} ${unit}`
                        },
                        backgroundColor: 'rgba(20,25,38,0.95)',
                        titleColor: '#fff', bodyColor: '#ddd', borderColor: '#3a3a5c', borderWidth: 1,
                    },
                },
                scales: {
                    x: { ticks: { color: '#888', font: { size: 10 } }, grid: { color: '#2a2a3e' } },
                    y: {
                        ticks: { color: '#888', font: { size: 10 }, callback: (v) => fmtAxis(v, unit) },
                        grid: { color: '#2a2a3e' },
                        title: { display: !!unit, text: unit, color: '#888', font: { size: 10 } },
                    },
                },
            };
        }

        function makeBarChart(id, labels, data, color, unit, label) {
            const ctx = document.getElementById(id); if (!ctx) return;
            const chart = new Chart(ctx, {
                type: 'bar',
                data: { labels, datasets: [{ label: label || '', data, backgroundColor: color + '99', borderColor: color, borderWidth: 1 }] },
                options: baseOpts(unit, label),
            });
            chartInstances.push(chart);
        }
        function makeLineChart(id, labels, data, color, unit, label) {
            const ctx = document.getElementById(id); if (!ctx) return;
            const chart = new Chart(ctx, {
                type: 'line',
                data: { labels, datasets: [{ label: label || '', data, borderColor: color, backgroundColor: color + '33', fill: true, tension: 0.25, pointBackgroundColor: color, pointRadius: 4 }] },
                options: baseOpts(unit, label),
            });
            chartInstances.push(chart);
        }


/* ===== EN 배너 (referrer/lang_pref 감지) ===== */
        // 영어 사용자 감지·기억 — referrer가 /en/* 또는 localStorage.lang_pref=en이면 안내 배너 표시
        function dismissEnBanner() {
            try { localStorage.setItem('lang_pref', 'ko'); } catch (e) {}
            var b = document.getElementById('enUserBanner');
            if (b) b.classList.add('is-hidden');
        }
        (function() {
            try {
                var pref = localStorage.getItem('lang_pref');
                var ref = document.referrer || '';
                var fromEn = ref.indexOf('/en/') !== -1 || ref.endsWith('/en');
                if (fromEn) {
                    localStorage.setItem('lang_pref', 'en');
                    pref = 'en';
                }
                if (pref === 'en') {
                    var banner = document.getElementById('enUserBanner');
                    if (banner) banner.classList.remove('is-hidden');
                }
            } catch (e) { /* localStorage 차단 환경 무시 */ }
        })();


/* ============================================================
 * 이벤트 위임 — onclick 인라인 핸들러 대체 (CSP·XSS 방어)
 * 모든 클릭 가능한 요소는 data-action="함수명" + 필요시 data-* 인자
 * ============================================================ */
(function setupEventDelegation() {
    // 액션 → 핸들러 매핑. el은 data-action을 가진 요소(closest 매치)
    const actions = {
        // 헤더·전역 UI
        toggleVolumeSidebar: () => toggleVolumeSidebar(),
        triggerInstall:      () => triggerInstall(),
        dismissEnBanner:     () => dismissEnBanner(),
        toggleLang:          () => setLang(getLang() === 'en' ? 'ko' : 'en'),
        // 거래량 사이드바
        refreshMostActive:   () => loadMostActive(true),
        switchVSTab:         (el) => switchVSTab(el.dataset.market),
        vsQuickAnalyze:      (el) => vsQuickAnalyze(el.dataset.ticker),
        // 동의 모달
        acceptConsent:       () => acceptConsent(),
        // 검색 + 퀵서치
        analyze:             () => analyze(),
        quickSearch:         (el) => quickSearch(el.dataset.ticker),
        clearHistory:        () => clearHistory(),
        // 일일 브리핑 모달
        closeBriefingModal:    () => closeBriefingModal(),
        dontShowBriefingToday: () => dontShowBriefingToday(),
        // 종목 상세 — 탭·즐겨찾기·공유
        switchTab:    (el) => switchTab(el.dataset.tab),
        toggleFavorite: () => toggleFavorite(),
        shareStock:   () => shareStock(),
        toggleCard:   (el) => toggleCard(parseInt(el.dataset.cardIdx, 10)),
        // lazy 로드 재시도
        retryNews:    () => { newsLoaded = false; loadNewsLazy(); },
        retryKrx:     () => { krxLoaded = false; loadKRXLazy(); },
    };

    document.addEventListener('click', (e) => {
        const target = e.target.closest('[data-action]');
        if (!target) return;
        const handler = actions[target.dataset.action];
        if (handler) {
            handler(target);
        } else if (typeof console !== 'undefined') {
            console.warn('[delegation] 알 수 없는 data-action:', target.dataset.action);
        }
    });
})();
