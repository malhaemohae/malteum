// Render each diagram HTML to a high-resolution PNG (SVG element only) with Chrome.
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('C:/Users/hanbin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const reports = [];
  for (const { slug, size } of JSON.parse(fs.readFileSync(path.join(__dirname, 'manifest.json'), 'utf8'))) {
    const [w, h] = size;
    const page = await browser.newPage({ viewport: { width: w + 80, height: h + 200 }, deviceScaleFactor: 3 });
    await page.goto(pathToFileURL(path.join(__dirname, slug + '.html')).href);
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(400);
    const report = await page.evaluate(([w, h]) => {
      const svg = document.querySelector('svg');
      const box = svg.getBoundingClientRect();
      const scale = box.width / w;
      const overflow = [];
      const texts = [...svg.querySelectorAll('text')];
      // getBBox ignores ancestor transforms; measure in screen space and map back to the viewBox.
      const bbox = (t) => { const r = t.getBoundingClientRect(); return { x: (r.left - box.left) / scale, y: (r.top - box.top) / scale, width: r.width / scale, height: r.height / scale }; };
      for (const t of texts) {
        const b = bbox(t);
        if (b.x < 0 || b.y < 0 || b.x + b.width > w || b.y + b.height > h) overflow.push('viewbox: ' + t.textContent);
      }
      // text overlapping another text (same diagram) is the most common legibility defect
      const rects = texts.map(t => ({ t: t.textContent, b: bbox(t) }));
      const overlaps = [];
      for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i].b, c = rects[j].b;
        if (a.x < c.x + c.width && c.x < a.x + a.width && a.y < c.y + c.height && c.y < a.y + a.height) overlaps.push(rects[i].t + ' <> ' + rects[j].t);
      }
      const fonts = [...new Set(texts.map(t => getComputedStyle(t).fontFamily))];
      return { overflow, overlaps, fonts, scale, geist: document.fonts.check('12px Geist'), serif: document.fonts.check('12px "Instrument Serif"') };
    }, [w, h]);
    await page.locator('svg').screenshot({ path: path.join(__dirname, slug + '.png'), omitBackground: false });
    reports.push({ slug, ...report });
    await page.close();
  }
  fs.writeFileSync(path.join(__dirname, 'render-check.json'), JSON.stringify(reports, null, 2));
  console.log(JSON.stringify(reports, null, 2));
  await browser.close();
  if (reports.some(r => r.overflow.length || r.overlaps.length)) process.exitCode = 1;
})().catch(e => { console.error(e); process.exitCode = 1; });
