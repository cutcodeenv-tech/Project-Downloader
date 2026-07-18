#!/usr/bin/env node
// Paper-pipeline web driver: given one or more article URLs (typed in or from a CSV),
// runs shot -> compose -> render for each and copies the finished ProRes-4444-alpha .mov
// into --out-dir. Designed to be spawned by the Flask app (web/app.py) and have its
// stdout streamed straight into the existing job-log UI: prints "=== Шаг N/M: ... ==="
// lines so the app's log parser (_parse_job_line_locked in web/app.py) tracks progress.
// A failure on one URL (bot-wall, non-Russian text, render error) is logged and the
// batch continues — never aborts the whole run.
//
// Usage:
//   node web_generate.mjs --urls-json '["https://…", "https://…"]' --out-dir /abs/path
//   node web_generate.mjs --csv /abs/path/links.csv --out-dir /abs/path

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const PAPER = path.dirname(fileURLToPath(import.meta.url));

function arg(n, d) {
  const i = process.argv.indexOf(`--${n}`);
  return i > -1 && process.argv[i + 1] && !process.argv[i + 1].startsWith("--") ? process.argv[i + 1] : d;
}
const outDir = arg("out-dir");
if (!outDir) {
  console.error("usage: node web_generate.mjs --urls-json '[...]' | --csv <path> --out-dir <dir>");
  process.exit(1);
}

function urlsFromCsv(csvPath) {
  const text = fs.readFileSync(csvPath, "utf8");
  const found = text.match(/https?:\/\/[^\s"',]+/g) || [];
  return [...new Set(found.map((u) => u.replace(/[.,;)\]]+$/, "")))];
}

let urls = [];
const urlsJson = arg("urls-json");
const csvPath = arg("csv");
if (urlsJson) {
  try {
    urls = JSON.parse(urlsJson).map(String).map((s) => s.trim()).filter(Boolean);
  } catch {
    console.error("--urls-json is not valid JSON");
    process.exit(1);
  }
} else if (csvPath) {
  if (!fs.existsSync(csvPath)) {
    console.error(`csv not found: ${csvPath}`);
    process.exit(1);
  }
  urls = urlsFromCsv(csvPath);
} else {
  console.error("usage: node web_generate.mjs --urls-json '[...]' | --csv <path> --out-dir <dir>");
  process.exit(1);
}
urls = [...new Set(urls)];
if (!urls.length) {
  console.error("no article URLs found");
  process.exit(1);
}

fs.mkdirSync(outDir, { recursive: true });

const slugify = (s) =>
  s.toLowerCase().replace(/[^a-z0-9а-яё]+/gi, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "article";
const shortHash = (s) => {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(h, 31) + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
};

let ok = 0, fail = 0, skipped = 0;
const N = urls.length;

for (let i = 0; i < N; i++) {
  const url = urls[i];
  const n = i + 1;
  console.log(`\n=== Шаг ${n}/${N}: ${url} ===`);

  const slug = `web-${shortHash(url)}`;
  const renderDir = path.join(PAPER, "renders", slug);

  try {
    execFileSync("node", [path.join(PAPER, "shot.mjs"), "--url", url, "--slug", slug], { stdio: "inherit" });
  } catch (e) {
    console.log(`✗ ошибка извлечения статьи: ${(e.message || e).toString().slice(0, 300)}`);
    fail++;
    continue;
  }

  const contentPath = path.join(renderDir, "source", "content.json");
  let content;
  try {
    content = JSON.parse(fs.readFileSync(contentPath, "utf8"));
  } catch {
    console.log(`✗ не удалось прочитать content.json`);
    fail++;
    continue;
  }
  if (!/[а-яё]/i.test(content.headline || "")) {
    console.log(`⚠ пропущено — текст не на русском, нужен перевод вручную: "${(content.headline || "").slice(0, 80)}"`);
    skipped++;
    continue;
  }

  try {
    execFileSync("node", [path.join(PAPER, "compose.mjs"), "--slug", slug], { stdio: "inherit" });
  } catch (e) {
    console.log(`✗ ошибка сборки: ${(e.message || e).toString().slice(0, 300)}`);
    fail++;
    continue;
  }

  const proresPath = path.join(PAPER, "renders", slug, `_render-${slug}.mov`);
  try {
    execFileSync("npx", ["--yes", "hyperframes", "render", renderDir, "--format", "mov", "--fps", "25", "-o", proresPath], { stdio: "inherit" });
  } catch (e) {
    console.log(`✗ ошибка рендера: ${(e.message || e).toString().slice(0, 300)}`);
    fail++;
    continue;
  }

  const finalName = `gazeta_article_${slugify(content.headline || slug)}_${Date.now()}.mov`;
  const finalPath = path.join(outDir, finalName);
  try {
    // QuickTime Animation (qtrle) with alpha — lossless, larger than ProRes 4444
    execFileSync("ffmpeg", ["-y", "-i", proresPath, "-c:v", "qtrle", "-pix_fmt", "argb", finalPath], { stdio: "inherit" });
    fs.rmSync(proresPath, { force: true });
  } catch (e) {
    console.log(`✗ ошибка транскода в QuickTime Animation: ${(e.message || e).toString().slice(0, 300)}`);
    fail++;
    continue;
  }

  console.log(`✓ готово -> ${finalName}`);
  ok++;
}

console.log(`\n=== Готово: ${ok} ок, ${fail} ошибок, ${skipped} пропущено (не рус. текст) ===`);
