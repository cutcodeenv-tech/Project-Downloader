#!/usr/bin/env node
// Paper-News compositor.
// Uses a real torn-paper Lottie template (data2..5.json) AS the paper — lightly edited:
//   image_1 -> plain cream (clean paper, no old site); every animated master null is
//   frozen at its settled value so WE drive the motion and content stays glued.
// The rebuilt article (kicker → animated headline → text, text-only, no images) FILLS the paper and is
// masked to the torn silhouette (auto-measured per template), then plays the storyboard:
//   appears in torn paper → pushes in → headline highlights → small scroll → drives off.
// Templates rotate 2→3→4→5→2… across runs when --template is omitted (Paper/.rotation).
// Font: SF Pro Text. Renders to a QuickTime .mov with alpha.
//
// Usage (after Paper/shot.mjs):
//   node Paper/compose.mjs --slug <slug> [--template 2|3|4|5] [--title "…"] [--accent "#e8352e"]

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const PAPER = path.dirname(fileURLToPath(import.meta.url));
const FOOT = path.join(PAPER, "footages");
const FONTS = path.join(PAPER, "Fonts");

function arg(n, d) {
  const i = process.argv.indexOf(`--${n}`);
  return i > -1 && process.argv[i + 1] && !process.argv[i + 1].startsWith("--") ? process.argv[i + 1] : d;
}
const slug = arg("slug");
if (!slug) {
  console.error("usage: node Paper/compose.mjs --slug <slug> [--template 2-5] [--title ...] [--accent #hex]");
  process.exit(1);
}
const accent = arg("accent", "#e8352e");

// ---- template rotation 2→3→4→5→2… (only when --template omitted) ----------
const ORDER = ["2", "3", "4", "5"];
const rotFile = path.join(PAPER, ".rotation");
let template = arg("template", "");
if (!template) {
  const last = fs.existsSync(rotFile) ? fs.readFileSync(rotFile, "utf8").trim() : "";
  template = ORDER[(ORDER.indexOf(last) + 1) % ORDER.length];
  fs.writeFileSync(rotFile, template);
} else if (!ORDER.includes(template)) {
  console.error(`--template must be one of ${ORDER.join(",")}`);
  process.exit(1);
}

// per-template storyboard motion (mimics each file's original entrance/exit)
const MOTION = {
  2: { in: { x: -1250, y: 0 }, out: { x: 1900, y: 0 } },     // from left → out right
  3: { in: { x: 0, y: 1200 }, out: { x: 0, y: 1200 } },      // from bottom → out bottom
  4: { in: { x: 1400, y: 0 }, out: { x: 1400, y: 0 } },      // from right → out right
  5: { in: { x: 1500, y: 0 }, out: { x: 1500, y: 0 } },      // from right → out right
}[template];
const STEP_FPS = 18; // stop-motion feel: animation time quantized to 18 steps/sec

const renderDir = path.join(PAPER, "renders", slug);
const srcDir = path.join(renderDir, "source");
const assetsDir = path.join(renderDir, "assets");
const imagesDir = path.join(renderDir, "images");
const fontsDir = path.join(assetsDir, "fonts");
const contentPath = path.join(srcDir, "content.json");
if (!fs.existsSync(contentPath)) {
  console.error(`missing ${contentPath} — run Paper/shot.mjs first`);
  process.exit(1);
}
const c = JSON.parse(fs.readFileSync(contentPath, "utf8"));
const headline = arg("title", c.headline) || slug;

fs.mkdirSync(imagesDir, { recursive: true });
fs.mkdirSync(fontsDir, { recursive: true });

// ---- edit the Lottie template into a clean, motion-neutral torn paper ------
// Freeze every animated null at its settled value = the value of the last
// keyframe at/before frame 100 (all four templates hold still around there).
function settled(prop, frame = 100) {
  if (!prop || prop.a !== 1) return null;
  let last = prop.k[0].s;
  for (const kf of prop.k) if (kf.t <= frame && kf.s) last = kf.s;
  return { a: 0, k: last };
}
function buildAnimation(dir) {
  const lot = JSON.parse(fs.readFileSync(path.join(PAPER, `data${template}.json`), "utf8"));
  execFileSync("ffmpeg", ["-y", "-f", "lavfi", "-i", "color=c=0xf4efe3:s=1920x1080", "-frames:v", "1", path.join(dir, "images", "img_1.png")], { stdio: "ignore" });
  fs.copyFileSync(path.join(FOOT, "GrungeTexture.jpg"), path.join(dir, "images", "img_0.jpg"));
  fs.copyFileSync(path.join(FOOT, "torn paper.png"), path.join(dir, "images", "img_2.png"));
  const a1 = lot.assets.find((a) => a.id === "image_1");
  a1.p = "img_1.png"; a1.w = 1920; a1.h = 1080; a1.u = "images/"; a1.e = 0;
  for (const l of lot.layers) {
    if (l.ty !== 3) continue; // nulls carry the master motion
    for (const ch of ["p", "s", "r"]) {
      const frozen = settled(l.ks[ch]);
      if (frozen) l.ks[ch] = frozen;
    }
  }
  fs.writeFileSync(path.join(dir, "animation.json"), JSON.stringify(lot));
}
buildAnimation(renderDir);

// ---- per-template mask + measured geometry (all cached in footages/) -------
const maskCache = path.join(FOOT, `paper-mask-${template}.png`);
const maskHard = path.join(FOOT, `paper-mask-${template}-hard.png`);
const geomCache = path.join(FOOT, `paper-geom-${template}.json`);

if (!fs.existsSync(maskCache)) {
  console.log(`  generating paper mask for template ${template} (one-time)…`);
  const tmp = path.join(PAPER, "_mask");
  fs.rmSync(tmp, { recursive: true, force: true });
  fs.mkdirSync(path.join(tmp, "images"), { recursive: true });
  buildAnimation(tmp);
  fs.writeFileSync(path.join(tmp, "hyperframes.json"), JSON.stringify({ paths: { blocks: ".", components: "components", assets: "." } }));
  fs.writeFileSync(path.join(tmp, "index.html"), `<!doctype html><html><head><meta charset=UTF-8>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/bodymovin/5.12.2/lottie.min.js"></script>
<style>html,body{margin:0;width:1920px;height:1080px;overflow:hidden;background:transparent}#l{width:1920px;height:1080px}</style></head>
<body><div id="main-composition" data-composition-id="main-video" data-width="1920" data-height="1080" data-start="0" data-duration="0.08">
<div id="l"></div><script>const a=lottie.loadAnimation({container:document.getElementById("l"),renderer:"svg",loop:false,autoplay:false,path:"animation.json"});window.__hfLottie=[a];window.__timelines={"main-video":gsap.timeline({paused:true})};</script>
</div></body></html>`);
  execFileSync("npx", ["--yes", "hyperframes", "render", tmp, "--format", "png-sequence", "--fps", "25", "-o", path.join(tmp, "seq")], { stdio: "ignore" });
  fs.copyFileSync(path.join(tmp, "seq", "frame_000001.png"), maskCache);
  fs.rmSync(tmp, { recursive: true, force: true });
}
if (!fs.existsSync(maskHard)) {
  // keep only fully-opaque paper (cut the drop shadow) so content never paints
  // over the semi-transparent shadow outside the torn silhouette
  execFileSync("ffmpeg", ["-y", "-i", maskCache, "-filter_complex",
    "[0]alphaextract,lut=y='if(gt(val,240),255,0)'[a];color=white:s=1920x1080:d=1[c];[c][a]alphamerge",
    "-frames:v", "1", maskHard], { stdio: "ignore" });
}
if (!fs.existsSync(geomCache)) {
  // measure the solid interior: per-row alpha scan of the hardened mask
  const raw = path.join(PAPER, `_alpha-${template}.raw`);
  execFileSync("ffmpeg", ["-y", "-i", maskHard, "-vf", "alphaextract", "-f", "rawvideo", "-pix_fmt", "gray", raw], { stdio: "ignore" });
  const W = 1920, H = 1080;
  const buf = fs.readFileSync(raw);
  fs.rmSync(raw);
  const rows = [];
  for (let y = 0; y < H; y++) {
    let l = -1, r = -1;
    for (let x = 0; x < W; x++) if (buf[y * W + x] > 240) { if (l < 0) l = x; r = x; }
    if (l >= 0) rows.push({ y, l, r });
  }
  if (!rows.length) { console.error("mask is empty — template render failed"); process.exit(1); }
  const y0 = rows[0].y, y1 = rows[rows.length - 1].y;
  const band = rows.filter((r) => r.y >= y0 + 40 && r.y <= y1 - 40);
  const maxL = Math.max(...band.map((r) => r.l));
  const minR = Math.min(...band.map((r) => r.r));
  fs.writeFileSync(geomCache, JSON.stringify({ y0, y1, maxL, minR }, null, 2));
  console.log(`  measured template ${template}: solid x[${maxL}..${minR}] y[${y0}..${y1}]`);
}
const G = JSON.parse(fs.readFileSync(geomCache, "utf8"));

// text column strictly inside the solid interior, margins off the torn edge
const COL = {
  left: G.maxL + 35,
  width: G.minR - 35 - (G.maxL + 35),
  padTop: G.y0 + 60,
  padBot: 1080 - G.y1 + 70,
};
// scale type to the column (baseline: 64px headline / 26px body at 690px width)
const K = Math.max(0.75, Math.min(1.15, COL.width / 690));
const FS = {
  headline: Math.round(64 * K),
  deck: Math.round(28 * K),
  body: Math.round(26 * K),
  kicker: Math.round(22 * Math.max(0.85, K)),
};

fs.copyFileSync(maskHard, path.join(assetsDir, "paper-mask.png"));

// fonts
for (const f of ["SFProText-Heavy.ttf", "SFProText-Bold.ttf", "SFProText-Semibold.ttf", "SFProText-Light.ttf"])
  if (fs.existsSync(path.join(FONTS, f))) fs.copyFileSync(path.join(FONTS, f), path.join(fontsDir, f));

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const words = headline.trim().split(/\s+/);
const DUR = 9.0;

fs.writeFileSync(path.join(renderDir, "hyperframes.json"), JSON.stringify({ paths: { blocks: ".", components: "components", assets: "." } }, null, 2));
fs.writeFileSync(path.join(renderDir, "meta.json"), JSON.stringify({ id: slug, name: headline, template }, null, 2));
fs.writeFileSync(path.join(renderDir, "index.html"), html());

console.log(`✓ composed data${template}.json + article -> renders/${slug}/index.html`);
console.log(`  template: ${template} (rotation)   headline: ${headline}`);
console.log(`  column: x${COL.left} w${COL.width} padT${COL.padTop} padB${COL.padBot}`);
console.log(`\nVerify:  npx hyperframes snapshot "Paper/renders/${slug}" --at 1,2.4,5,7.5 --no-end`);
console.log(`Render:  npx hyperframes render "Paper/renders/${slug}" --format mov --fps 25 -o "out/_prores-${slug}.mov"`);
console.log(`         ffmpeg -y -i "out/_prores-${slug}.mov" -c:v qtrle -pix_fmt argb "out/${slug}.mov" && rm "out/_prores-${slug}.mov"\n`);

function bodyHtml() {
  const key = (s) => String(s).replace(/[«»"'`]/g, "").replace(/\s+/g, " ").trim().slice(0, 70).toLowerCase();
  const deckKey = key(c.deck || "");
  const paras = (c.paragraphs || []).filter((p) => key(p) !== deckKey); // drop the deck echo
  return paras.slice(0, 9).map((p) => `<p class="body-p">${esc(p)}</p>`).join("\n            ");
}

function html() {
  return `<!doctype html>
<html lang="ru"><head><meta charset="UTF-8" /><title>${esc(headline)}</title>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/bodymovin/5.12.2/lottie.min.js"></script>
<style>
  @font-face { font-family:"SFPro"; src:url("assets/fonts/SFProText-Heavy.ttf"); font-weight:800; }
  @font-face { font-family:"SFPro"; src:url("assets/fonts/SFProText-Bold.ttf"); font-weight:700; }
  @font-face { font-family:"SFPro"; src:url("assets/fonts/SFProText-Semibold.ttf"); font-weight:600; }
  @font-face { font-family:"SFPro"; src:url("assets/fonts/SFProText-Light.ttf"); font-weight:300; }
  * { box-sizing:border-box; }
  html,body { margin:0; padding:0; width:1920px; height:1080px; overflow:hidden; background:transparent; font-family:"SFPro",sans-serif; }
  #stage { position:relative; width:1920px; height:1080px; overflow:hidden; }
  #camera { position:absolute; inset:0; transform-origin:${Math.round((COL.left + COL.width / 2) / 19.2)}% 50%; }
  #group { position:absolute; inset:0; }
  #paper-lottie { position:absolute; inset:0; width:1920px; height:1080px; z-index:1; }

  /* content fills the WHOLE paper, masked to the torn silhouette */
  #content { position:absolute; inset:0; width:1920px; height:1080px; z-index:2; overflow:hidden;
    -webkit-mask-image:url("assets/paper-mask.png"); -webkit-mask-size:1920px 1080px; -webkit-mask-repeat:no-repeat; -webkit-mask-position:0 0;
    mask-image:url("assets/paper-mask.png"); mask-size:1920px 1080px; mask-repeat:no-repeat; mask-position:0 0; }
  #scroll { position:absolute; left:${COL.left}px; top:0; width:${COL.width}px; padding:${COL.padTop}px 0 ${COL.padBot}px; }

  .kicker { font-weight:700; font-size:${FS.kicker}px; letter-spacing:2.5px; text-transform:uppercase; color:${accent}; margin-bottom:20px; display:flex; gap:12px; align-items:center; }
  .kicker .rule { flex:0 0 50px; height:6px; background:${accent}; }
  .head-wrap { position:relative; display:inline-block; padding:1px 12px 8px 0; }
  .hl { position:absolute; left:-9px; top:2px; right:-4px; bottom:7px; background:#ff8c00; transform:scaleX(0); transform-origin:left center; z-index:0; }
  h1.headline { position:relative; z-index:1; margin:0; font-weight:800; font-size:${FS.headline}px; line-height:1.04; letter-spacing:-1.5px; color:#17140f; }
  h1.headline .w { display:inline-block; overflow:hidden; vertical-align:top; }
  h1.headline .w > span { display:inline-block; }
  .under { height:${Math.max(7, Math.round(11 * K))}px; width:100%; background:#17140f; transform:scaleX(0); transform-origin:left center; margin:18px 0 26px; }
  .deck { font-weight:300; font-size:${FS.deck}px; line-height:1.3; color:#3b342a; margin:0 0 28px; }
  .body-p { font-weight:300; font-size:${FS.body}px; line-height:1.5; color:#221e18; margin:0 0 22px; }
</style></head>
<body>
  <div id="stage" data-composition-id="main-video" data-width="1920" data-height="1080" data-start="0" data-duration="${DUR}">
    <div id="camera"><div id="group">
      <div id="paper-lottie"></div>
      <div id="content"><div id="scroll">
        <div class="kicker"><span class="rule"></span>${esc((c.source || "").toUpperCase())}${c.kicker ? " · " + esc(c.kicker.toUpperCase()) : ""}</div>
        <div class="head-wrap"><div class="hl"></div><h1 class="headline">${words.map((w) => `<span class="w"><span>${esc(w)}</span></span>`).join(" ")}</h1></div>
        <div class="under"></div>
        ${c.deck ? `<p class="deck">${esc(c.deck)}</p>` : ""}
        ${bodyHtml()}
      </div></div>
    </div></div>

    <script>
      const paper = lottie.loadAnimation({ container: document.getElementById("paper-lottie"), renderer:"svg", loop:false, autoplay:false, path:"animation.json" });
      window.__hfLottie = window.__hfLottie || []; window.__hfLottie.push(paper);

      // inner timeline = the real animation; outer timeline quantizes it to
      // ${STEP_FPS} steps/sec for a subtle stop-motion feel (seek-safe)
      const anim = gsap.timeline({ paused:true });

      gsap.set("#group", { x:${MOTION.in.x}, y:${MOTION.in.y} });
      gsap.set("#camera", { scale:0.95 });
      gsap.set(".kicker", { opacity:0, y:14 });
      gsap.set("h1.headline .w > span", { yPercent:115 });
      gsap.set(".hl", { scaleX:0 });
      gsap.set(".under", { scaleX:0 });
      gsap.set(".deck, .body-p", { opacity:0, y:12 });

      // 1) появляется в рваной бумаге
      anim.to("#group", { x:0, y:0, duration:0.55, ease:"power3.out" }, 0.0);
      // 2) приближается
      anim.to("#camera", { scale:1.05, duration:2.3, ease:"power2.out" }, 0.5);
      // 3) заголовок появляется во время движения бумаги (не после)
      anim.to(".kicker", { opacity:1, y:0, duration:0.35 }, 0.05);
      anim.to(".hl", { scaleX:1, duration:0.4, ease:"power3.inOut" }, 0.1);
      anim.to("h1.headline .w > span", { yPercent:0, duration:0.4, ease:"power3.out", stagger:0.03 }, 0.15);
      // 4) подчёркивание — сразу как бумага долетела (0.55s = конец движения)
      anim.to(".under", { scaleX:1, duration:0.4, ease:"power2.out" }, 0.55);
      anim.to(".deck, .body-p", { opacity:1, y:0, duration:0.5, stagger:0.04 }, 0.9);
      // 5) небольшой скрол — дистанция считается лениво (после загрузки фото),
      //    иначе scrollHeight занижен и скролла не будет (баг на широких шаблонах)
      const scroll = document.getElementById("scroll");
      anim.to(scroll, {
        y: () => -Math.min(Math.max(0, scroll.scrollHeight - 1080), 620),
        duration:2.8, ease:"power1.inOut",
      }, 3.0);
      // 6) уезжает
      anim.to("#group", { x:${MOTION.out.x}, y:${MOTION.out.y}, duration:0.6, ease:"power2.in" }, 8.2);

      // stop-motion driver: HyperFrames seeks tl; tl snaps anim to ${STEP_FPS}fps grid
      const STEP = 1 / ${STEP_FPS};
      const tl = gsap.timeline({ paused:true });
      tl.to({ t:0 }, { t:${DUR}, duration:${DUR}, ease:"none",
        onUpdate() { anim.time(Math.min(${DUR}, Math.floor(tl.time() / STEP) * STEP)); } });
      window.__timelines = window.__timelines || {}; window.__timelines["main-video"] = tl;
    </script>
  </div>
</body></html>
`;
}
