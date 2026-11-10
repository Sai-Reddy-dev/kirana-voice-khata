// Caches only the app shell and same-origin static assets. API responses and
// non-GET requests are never cached or queued.

const CACHE_PREFIX = "kvk-";
const SHELL_CACHE = `${CACHE_PREFIX}v2-shell`;
const APP_SCOPE = self.registration.scope;

function scopedUrl(path) {
  return new URL(path, APP_SCOPE).href;
}

async function installAppShell() {
  const indexUrl = scopedUrl("index.html");
  const response = await fetch(indexUrl, { cache: "reload" });
  if (!response.ok) {
    throw new Error(`Unable to precache app entry point: HTTP ${response.status}`);
  }

  const html = await response.text();
  const builtAssets = [...html.matchAll(/(?:src|href)=["']([^"']+\.(?:m?js|css))(?:\?[^"']*)?["']/gi)]
    .map((match) => new URL(match[1], indexUrl))
    .filter((assetUrl) => assetUrl.origin === self.location.origin)
    .map((assetUrl) => assetUrl.href);
  if (builtAssets.length === 0) {
    throw new Error("Unable to find production JavaScript or CSS assets in index.html");
  }

  const cache = await caches.open(SHELL_CACHE);
  await cache.put(indexUrl, response.clone());
  await cache.put(scopedUrl(""), response.clone());
  await cache.addAll([
    ...builtAssets,
    scopedUrl("manifest.json"),
    scopedUrl("icons/icon-192.png"),
    scopedUrl("icons/icon-512.png"),
  ]);
}

self.addEventListener("install", (event) => {
  event.waitUntil(installAppShell());
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith(CACHE_PREFIX) && key !== SHELL_CACHE)
          .map((key) => caches.delete(key)),
      ),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const requestUrl = new URL(request.url);
  if (requestUrl.origin !== self.location.origin) return;

  if (requestUrl.pathname === "/api" || requestUrl.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(request).catch(
        () =>
          new Response(
            JSON.stringify({ detail: "OFFLINE", message: "Server unavailable." }),
            {
              status: 503,
              headers: { "Content-Type": "application/json" },
            },
          ),
      ),
    );
    return;
  }

  const isNavigation = request.mode === "navigate";
  const isShellAsset =
    requestUrl.pathname.startsWith("/assets/") ||
    requestUrl.pathname.startsWith("/icons/") ||
    ["/manifest.json", "/service-worker.js"].includes(requestUrl.pathname);
  if (!isNavigation && !isShellAsset) return;

  const refresh = caches.open(SHELL_CACHE).then((cache) =>
    fetch(request).then((response) => {
        if (response.ok) {
          return cache.put(request, response.clone()).then(() => response);
        }
        return response;
      }),
  );
  event.waitUntil(refresh.then(() => undefined, () => undefined));

  event.respondWith(
    caches.open(SHELL_CACHE).then(async (cache) => {
      const cached = await cache.match(request);
      if (cached) return cached;
      try {
        return await refresh;
      } catch (error) {
        if (isNavigation) {
          const fallback = await cache.match(scopedUrl("index.html"));
          if (fallback) return fallback;
        }
        throw error;
      }
    }),
  );
});
