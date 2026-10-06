/* Service worker de Comandia: guarda la pantalla (index, scripts y estilos) para poder abrirla aunque el servidor no responda.
   Primero intenta la red (así las actualizaciones llegan solas) y, si falla o tarda, usa la copia guardada. Nunca guarda /api/. */
const CACHE = "comandia-shell-v1";
const NETWORK_WAIT_MS = 3000;

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then((cache) => cache.add("/")).catch(() => {}));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (url.pathname !== "/" && !url.pathname.startsWith("/static/")) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const fromCache = async () => (await cache.match(req)) || (await cache.match(req, { ignoreSearch: true })) || (req.mode === "navigate" ? await cache.match("/") : undefined);
    try {
      const res = await Promise.race([
        fetch(req, { cache: "no-cache" }),
        new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), NETWORK_WAIT_MS)),
      ]);
      if (res && res.ok) cache.put(req, res.clone());
      return res;
    } catch (err) {
      return (await fromCache()) || Response.error();
    }
  })());
});
