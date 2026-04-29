/**
 * StockInto 인라인 용어 툴팁.
 *
 * 동작:
 * - 데스크톱: mouseenter → 0.2초 지연 후 말풍선 표시, mouseleave → 닫힘
 * - 모바일: tap → 표시, 바깥 tap/ESC → 닫힘
 * - 같은 용어 한 페이지 내 여러 번 등장 OK (각 span 독립)
 *
 * 사용:
 *   StockIntoTooltip.markup(htmlOrElement)  // 텍스트의 용어를 자동 마킹
 *   StockIntoTooltip.attach(rootElement)    // 마킹된 노드에 이벤트 부착
 */
(function () {
  const TERMS = window.STOCKINTO_TERMS || {};
  const TERM_KEYS = Object.keys(TERMS);

  // 길이 내림차순 정렬 — "P/S"가 "P"보다 먼저 매칭되도록
  TERM_KEYS.sort((a, b) => b.length - a.length);

  // 정규식 escape
  function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&'); }

  // 단어 경계 정의: 영문 용어는 \b 사용, 한글 용어는 비단어 경계
  const HAS_HANGUL = /[가-힯]/;
  function buildPattern() {
    const parts = TERM_KEYS.map(k => {
      const escaped = escRe(k);
      if (HAS_HANGUL.test(k)) {
        return escaped;
      }
      // 영문/숫자: 앞뒤가 영문·숫자가 아닐 때만 매칭
      return `(?<![A-Za-z0-9])${escaped}(?![A-Za-z0-9])`;
    });
    return new RegExp('(' + parts.join('|') + ')', 'g');
  }

  let TERM_RE = null;
  try {
    TERM_RE = buildPattern();
  } catch (e) {
    // 일부 구형 브라우저는 lookbehind 미지원 → 단순 패턴 fallback
    TERM_RE = new RegExp('(' + TERM_KEYS.map(escRe).join('|') + ')', 'g');
  }

  // HTML escape
  function escHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /**
   * HTML 문자열의 텍스트 노드만 골라 용어를 <span>으로 감쌈.
   * 태그 속성 안의 텍스트는 건드리지 않음.
   */
  function markupHtml(html) {
    if (!html || !TERM_KEYS.length) return html;
    // 태그(<...>)와 텍스트를 분리
    const out = [];
    let i = 0;
    while (i < html.length) {
      if (html[i] === '<') {
        const end = html.indexOf('>', i);
        if (end === -1) { out.push(html.slice(i)); break; }
        out.push(html.slice(i, end + 1));
        i = end + 1;
      } else {
        const next = html.indexOf('<', i);
        const text = next === -1 ? html.slice(i) : html.slice(i, next);
        out.push(text.replace(TERM_RE, (m) => {
          const key = TERMS[m] ? m : null;
          if (!key) return m;
          return `<span class="term-tooltip" data-term="${escHtml(m)}" tabindex="0" role="button" aria-label="${escHtml(m)} 설명 보기">${escHtml(m)}</span>`;
        }));
        i = next === -1 ? html.length : next;
      }
    }
    return out.join('');
  }

  // ========== 툴팁 표시 로직 ==========
  let tooltipEl = null;
  let activeTrigger = null;
  let hoverTimer = null;

  function ensureTooltip() {
    if (tooltipEl) return tooltipEl;
    tooltipEl = document.createElement('div');
    tooltipEl.className = 'term-tooltip-popup';
    tooltipEl.setAttribute('role', 'tooltip');
    tooltipEl.style.display = 'none';
    document.body.appendChild(tooltipEl);
    return tooltipEl;
  }

  function showTooltip(trigger) {
    const term = trigger.getAttribute('data-term');
    const data = TERMS[term];
    if (!data || !data.def) return;
    const el = ensureTooltip();
    const moreHref = data.more ? `/glossary#${data.more}` : '/glossary';
    el.innerHTML = `
      <div class="ttp-head"><b>${escHtml(term)}</b></div>
      <div class="ttp-body">${escHtml(data.def)}</div>
      <a class="ttp-link" href="${moreHref}">용어 사전에서 더 보기 →</a>
    `;
    el.style.display = 'block';
    positionTooltip(trigger, el);
    activeTrigger = trigger;
    trigger.classList.add('term-active');
  }

  function positionTooltip(trigger, el) {
    const r = trigger.getBoundingClientRect();
    const elW = Math.min(el.offsetWidth || 280, window.innerWidth - 24);
    el.style.maxWidth = elW + 'px';
    let left = r.left + r.width / 2 - elW / 2;
    left = Math.max(12, Math.min(left, window.innerWidth - elW - 12));
    let top = r.bottom + 8;
    // 화면 아래로 넘치면 위에 표시
    if (top + el.offsetHeight > window.innerHeight - 12) {
      top = r.top - el.offsetHeight - 8;
    }
    el.style.left = (left + window.scrollX) + 'px';
    el.style.top = (top + window.scrollY) + 'px';
  }

  function hideTooltip() {
    if (tooltipEl) tooltipEl.style.display = 'none';
    if (activeTrigger) activeTrigger.classList.remove('term-active');
    activeTrigger = null;
  }

  // 이벤트 위임
  let touchHandled = false;  // touchend가 처리됐으면 click 무시 (이중 발화 방지)
  function attachGlobal() {
    document.addEventListener('mouseover', (e) => {
      const t = e.target.closest('.term-tooltip');
      if (!t) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(() => showTooltip(t), 180);
    });
    document.addEventListener('mouseout', (e) => {
      const t = e.target.closest('.term-tooltip');
      if (!t) return;
      clearTimeout(hoverTimer);
      // 툴팁 위로 이동한 경우는 유지
      const to = e.relatedTarget;
      if (to && (to.closest && to.closest('.term-tooltip-popup'))) return;
      hideTooltip();
    });
    // 모바일 터치: touchend로 즉시 반응 (300ms 지연 없음)
    document.addEventListener('touchend', (e) => {
      const t = e.target.closest && e.target.closest('.term-tooltip');
      if (t) {
        e.preventDefault();
        touchHandled = true;
        setTimeout(() => { touchHandled = false; }, 500);
        if (activeTrigger === t) hideTooltip(); else showTooltip(t);
        return;
      }
      // 바깥 터치 → 닫힘
      if (activeTrigger && !(e.target.closest && e.target.closest('.term-tooltip-popup'))) {
        hideTooltip();
      }
    }, { passive: false });
    // 마우스/키보드 클릭 (터치 후 발생하는 click은 무시)
    document.addEventListener('click', (e) => {
      if (touchHandled) return;
      const t = e.target.closest('.term-tooltip');
      if (t) {
        e.preventDefault();
        if (activeTrigger === t) hideTooltip(); else showTooltip(t);
        return;
      }
      if (activeTrigger && !e.target.closest('.term-tooltip-popup')) {
        hideTooltip();
      }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') hideTooltip();
      if (e.key === 'Enter' || e.key === ' ') {
        const t = document.activeElement;
        if (t && t.classList && t.classList.contains('term-tooltip')) {
          e.preventDefault();
          if (activeTrigger === t) hideTooltip(); else showTooltip(t);
        }
      }
    });
    window.addEventListener('resize', hideTooltip);
    // scroll 시 위치 재계산 (즉시 닫지 않음 — 모바일 스크롤로 사라지면 답답)
    let scrollT = null;
    window.addEventListener('scroll', () => {
      if (!activeTrigger || !tooltipEl || tooltipEl.style.display === 'none') return;
      clearTimeout(scrollT);
      scrollT = setTimeout(() => positionTooltip(activeTrigger, tooltipEl), 50);
    }, { passive: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attachGlobal);
  } else {
    attachGlobal();
  }

  window.StockIntoTooltip = {
    markup: markupHtml,
    hide: hideTooltip,
  };
})();
