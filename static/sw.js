// StockInto Service Worker - v46 (📅 데이터 기준일 전면 표기 — 종목 헤더·평가자·적정가·푸터 + dataMeta 메타 시스템)
// 메인 HTML은 캐시 안 함 (항상 최신 JS/CSS 받도록)
const CACHE_NAME = 'stockinto-v46';
const STATIC_ASSETS = [
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // API 요청은 네트워크 우선, 실패 시 에러
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).catch(() => new Response(
        JSON.stringify({ error: '오프라인 상태입니다' }),
        { headers: { 'Content-Type': 'application/json' }, status: 503 }
      ))
    );
    return;
  }

  // 메인 HTML 페이지(/, /install, /terms, /privacy)는 항상 네트워크에서 받기
  // (캐시하지 않음 → 업데이트 즉시 반영)
  if (req.destination === 'document') {
    event.respondWith(
      fetch(req).catch(() => caches.match('/static/manifest.json'))
    );
    return;
  }

  // 정적 자원(이미지·아이콘)만 캐시 우선
  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((res) => {
        if (res.ok && res.type === 'basic') {
          const resClone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(req, resClone));
        }
        return res;
      });
    })
  );
});
