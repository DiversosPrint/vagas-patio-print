const CACHE_NAME = 'vagas-print-v1.2';

const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/login.html',
  '/manifest.json',
  '/imagens/logo-print.png',
  '/imagens/icon-192.png',
  '/imagens/icon-512.png',
  '/imagens/apple-touch-icon.png',
  '/imagens/patio-print-sem-veiculos.png',
  '/imagens/Axor%202038.webp',
  '/imagens/19360.webp',
  '/imagens/Conjunto%20com%20Axor.webp',
  '/imagens/Conjunto%20com%20Scania.webp',
  '/imagens/Conjunto%20com%20Volks.webp',
  '/imagens/Carreta.webp'
];

// Instalação do Service Worker e pré-carregamento do cache
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS).catch(err => {
        console.warn('Alguns assets falharam no pre-cache:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// Ativação e limpeza de caches antigos
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

// Estratégia de Fetch:
// - Para /api/: Network-First com fallback de Cache para funcionamento offline
// - Para assets estáticos: Stale-While-Revalidate / Cache-First
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // Não intercepta requisições não-GET
  if (req.method !== 'GET') return;

  // Rotas de API: Tenta rede primeiro, grava no cache se tiver sucesso, usa cache se offline
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).then(networkResponse => {
        if (networkResponse && networkResponse.status === 200) {
          const resClone = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(req, resClone));
        }
        return networkResponse;
      }).catch(() => {
        return caches.match(req);
      })
    );
    return;
  }

  // Assets estáticos: Cache primeiro, depois rede (Stale-While-Revalidate)
  event.respondWith(
    caches.match(req).then(cachedResponse => {
      const fetchPromise = fetch(req).then(networkResponse => {
        if (networkResponse && networkResponse.status === 200) {
          const resClone = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(req, resClone));
        }
        return networkResponse;
      }).catch(() => cachedResponse);

      return cachedResponse || fetchPromise;
    })
  );
});
