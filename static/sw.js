// StockInto Service Worker - 오프라인 캐시 + 네트워크 우선
const CACHE_NAME = 'stockinto-v2';
const STATIC_ASSETS = [
  '/',
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

  // API 요청은 네트워크 우선, 실패 시 캐시 없음
  if (req.url.includes('/api/')) {
    event.respondWith(
      fetch(req).catch(() => new Response(
        JSON.stringify({ error: '오프라인 상태입니다' }),
        { headers: { 'Content-Type': 'application/json' }, status: 503 }
      ))
    );
    return;
  }

  // 정적 자원은 캐시 우선, 없으면 네트워크
  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((res) => {
        // 성공적인 GET은 캐시에 추가
        if (res.ok && res.type === 'basic') {
          const resClone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(req, resClone));
        }
        return res;
      }).catch(() => caches.match('/'));
    })
  );
});
