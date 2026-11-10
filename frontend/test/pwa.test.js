import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const distDir = path.join(frontendDir, "dist");

test("production HTML asset URLs exist in the Vite build output", (context) => {
  const indexPath = path.join(distDir, "index.html");
  if (!existsSync(indexPath)) {
    context.skip("Run npm run build before checking production PWA output.");
    return;
  }
  const html = readFileSync(indexPath, "utf8");
  const assetPaths = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+\.(?:m?js|css))"/g)]
    .map((match) => match[1]);

  assert.ok(assetPaths.some((assetPath) => assetPath.endsWith(".js")));
  assert.ok(assetPaths.some((assetPath) => assetPath.endsWith(".css")));
  for (const assetPath of assetPaths) {
    assert.ok(existsSync(path.join(distDir, assetPath.slice(1))), `${assetPath} is missing`);
  }
});

test("production manifest icons and service worker paths match emitted files", (context) => {
  const manifestPath = path.join(distDir, "manifest.json");
  const workerPath = path.join(distDir, "service-worker.js");
  if (!existsSync(manifestPath) || !existsSync(workerPath)) {
    context.skip("Run npm run build before checking production PWA output.");
    return;
  }

  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const worker = readFileSync(workerPath, "utf8");
  assert.equal(manifest.display, "standalone");
  assert.equal(manifest.theme_color, "#1B5E20");
  assert.equal(manifest.scope, "./");
  for (const icon of manifest.icons.filter((entry) => ["192x192", "512x512"].includes(entry.sizes))) {
    const iconPath = path.join(distDir, icon.src);
    assert.ok(existsSync(iconPath), `${icon.src} is missing`);
    const bytes = readFileSync(iconPath);
    assert.equal(bytes.readUInt32BE(16), Number.parseInt(icon.sizes.split("x")[0], 10));
    assert.equal(bytes.readUInt32BE(20), Number.parseInt(icon.sizes.split("x")[1], 10));
  }
  assert.match(worker, /matchAll\(\/\(\?:src\|href\)=/);
  assert.match(worker, /\/api\//);
  assert.match(worker, /request\.method !== "GET"/);
  assert.match(readFileSync(path.join(frontendDir, "app.js"), "utf8"), /register\("\/service-worker\.js", \{ scope: "\/" \}\)/);
});
