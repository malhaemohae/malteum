const fs = require('node:fs');
const assert = require('node:assert/strict');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  }).outputText, filename);
}
const { landingPreview } = require('../lib/landing-preview.ts');
const messages = require('../../back/contracts/fixtures/ws_messages.json');
const pack = require('../../back/contracts/fixtures/rulepack_DEP-2026.08-v6.json');
const events = require('../../back/contracts/fixtures/events_scenario_a.json');
const Landing = require('../components/marketing-showcase.tsx').default;
let starts = 0;
const html = renderToStaticMarkup(React.createElement(Landing, { onStart: () => starts++, onNavigate: () => {} }));
assert.equal(starts, 0, 'Rendering the landing must not start a session or recording');
assert.deepEqual(landingPreview.summary, messages.find(event => event.t === 'ended').summary);
assert.deepEqual(landingPreview.evidence, pack.items.find(item => item.code === 'DEP-INT-002').evidence);
assert.equal(landingPreview.itemName, pack.items.find(item => item.code === 'DEP-INT-002').name);
assert.equal(landingPreview.customer, events.find(event => event.event_id === 'FIXT-EV-0014').utterance.text);
assert.equal(landingPreview.teller, events.find(event => event.event_id === 'FIXT-EV-0017').utterance.text);
assert.equal(landingPreview.guidance, messages.find(event => event.t === 'assist' && event.seq === 7).text);
for (const text of [landingPreview.customer, landingPreview.guidance, landingPreview.evidence.span]) assert.ok(html.includes(text));
assert.equal((html.match(/class="mlp-example"/g) || []).length, 4, 'Every illustration is labelled as an example');
const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map(match => match[1]);
assert.equal(new Set(ids).size, ids.length, 'No duplicate anchor IDs');
for (const match of html.matchAll(/href="#([^"]+)"/g)) assert.ok(ids.includes(match[1]), `Missing anchor ${match[1]}`);
assert.equal((html.match(/class="mlp-start/g) || []).length, 3);
assert.ok(!/landing-relaunch|feature-signal|record-art|tutorial-focus/.test(html), 'No legacy abstract art or landing tutorial');
console.log('PASS: grounded preview quotes/pages/totals, example labels, anchors, shared start CTA, no landing recording/tutorial.');
