#!/usr/bin/env node
// Paper-News extractor. Disassembles a news article into clean parts so it can be
// REBUILT into our own layout (headline + image + text) — never a raw screenshot.
// Drives the already-installed Google Chrome via puppeteer-core (no browser download).
//
// Usage:
//   node Paper/shot.mjs --url https://site/article --slug my-news
//
// Writes into Paper/renders/<slug>/source/:
//   content.json  { source, kicker, headline, deck, paragraphs[] }  -- text only, no images

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const PAPER = path.dirname(fileURLToPath(import.meta.url));

function arg(name, def) {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : def;
}
const url = arg("url");
const slug = arg("slug");
if (!url || !slug) {
  console.error("usage: node Paper/shot.mjs --url <url> --slug <slug>");
  process.exit(1);
}

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const outDir = path.join(PAPER, "renders", slug, "source");
fs.mkdirSync(outDir, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "shell",
  args: ["--no-sandbox", "--hide-scrollbars"],
});

try {
  const page = await browser.newPage();
  await page.setUserAgent(
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
  );
  await page.setExtraHTTPHeaders({ "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8" });
  await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 });
  // domcontentloaded is far more reliable than networkidle2 on ad-heavy news sites;
  // tolerate a nav timeout (the DOM is usually there anyway), then settle briefly
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  } catch {
    /* proceed with whatever loaded */
  }
  // absorb a bot-protection JS redirect/reload (else "execution context destroyed")
  await page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 6000 }).catch(() => {});
  await new Promise((r) => setTimeout(r, 1800));

  // trigger lazy images (best-effort; ignore if a navigation interrupts it)
  await page
    .evaluate(async () => {
      await new Promise((res) => {
        let y = 0;
        const t = setInterval(() => {
          window.scrollBy(0, 800);
          y += 800;
          if (y >= document.body.scrollHeight) {
            clearInterval(t);
            window.scrollTo(0, 0);
            res();
          }
        }, 50);
      });
    })
    .catch(() => {});
  await new Promise((r) => setTimeout(r, 600));

  const extract = () => page.evaluate(() => {
    const meta = (sel, attr = "content") => {
      const el = document.querySelector(sel);
      return el ? (el.getAttribute(attr) || "").trim() : "";
    };
    const txt = (sel) => {
      const el = document.querySelector(sel);
      return el ? (el.textContent || "").trim() : "";
    };
    const headline = meta('meta[property="og:title"]') || txt("h1") || document.title;
    const deck =
      meta('meta[property="og:description"]') || meta('meta[name="description"]');
    const source = meta('meta[property="og:site_name"]') || location.hostname.replace(/^www\./, "");
    // rubric from the URL path segment (deterministic; avoids grabbing nav menus)
    const RUB = {
      politics: "Политика", policy: "Политика", business: "Бизнес", economics: "Экономика",
      economy: "Экономика", finance: "Финансы", finances: "Финансы", society: "Общество",
      social: "Общество", tech: "Технологии", technology: "Технологии", technology_and_media: "Технологии и медиа",
      science: "Наука", world: "В мире", incidents: "Происшествия", culture: "Культура",
      sport: "Спорт", sports: "Спорт", auto: "Авто", retail: "Ритейл", media: "Медиа",
    };
    let kicker = "";
    for (const seg of location.pathname.split("/")) {
      if (RUB[seg.toLowerCase()]) { kicker = RUB[seg.toLowerCase()]; break; }
    }

    // article body: prefer a real article container, then widen; length-filter <p>.
    const containers = ["article", '[itemprop="articleBody"]', '[class*="article" i]',
      '[class*="content" i]', "main", "body"];
    const clean = (p) => (p.textContent || "").replace(/\s+/g, " ").trim();
    const good = (t) => t.length > 45 && t.split(" ").length > 6;
    let paragraphs = [];
    for (const sel of containers) {
      const root = document.querySelector(sel);
      if (!root) continue;
      paragraphs = Array.from(root.querySelectorAll("p")).map(clean).filter(good);
      if (paragraphs.length >= 3) break;
    }
    // last resort: every <p> on the page
    if (paragraphs.length < 2) {
      paragraphs = Array.from(document.querySelectorAll("p")).map(clean).filter(good);
    }
    paragraphs = [...new Set(paragraphs)].slice(0, 12);

    return { source, kicker, headline, deck, paragraphs };
  });

  // retry once if the first extract hit a redirect (destroyed context)
  let data;
  try {
    data = await extract();
  } catch {
    await new Promise((r) => setTimeout(r, 1800));
    data = await extract();
  }

  // reject bot walls / error pages so they never become a garbage video
  const wall = /forbidden|access denied|attention required|just a moment|checking your browser|проверка браузера|доступ ограничен|ошибка 4\d\d|error 4\d\d|^403|^404|are you a robot|enable javascript/i;
  const thin = !data.deck && data.paragraphs.length === 0;
  if (wall.test(data.headline) || (thin && (!data.headline || data.headline.length < 12))) {
    throw new Error(`interstitial/empty page: "${(data.headline || "").slice(0, 60)}"`);
  }

  fs.writeFileSync(path.join(outDir, "content.json"), JSON.stringify(data, null, 2));

  console.log(`✓ extracted ${slug}`);
  console.log(`  source:   ${data.source}${data.kicker ? " / " + data.kicker : ""}`);
  console.log(`  headline: ${data.headline}`);
  console.log(`  paras:    ${data.paragraphs.length}`);
} finally {
  await browser.close();
}
