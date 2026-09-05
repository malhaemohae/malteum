// Run snapshot, restart the local DB/backend, then run verify.
// Select only the synthetic sessions produced by workspace-qa; never modify records.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const output = path.resolve(__dirname, '../qa-output');
const base = process.env.QA_BASE_URL || 'http://127.0.0.1:3000';
const mode = process.argv[2];
const snapshotPath = path.join(output, 'persistence-before.json');
async function get(resource) {
  const response = await fetch(base + '/api' + resource, { signal: AbortSignal.timeout(15000) });
  assert.equal(response.status, 200, resource);
  return response.json();
}
async function session(id) {
  const detail = await get(`/sessions/${id}`);
  assert.equal(detail.status, 'ended');
  const events = new Map(); let cursor = 0;
  for (;;) {
    const page = await get(`/sessions/${id}/events?from_seq=${cursor}`);
    for (const event of page.events) events.set(event.event_id, event);
    if (!page.truncated) break;
    const next = Math.max(...page.events.map(event => event.seq_in_session));
    assert.ok(next > cursor, 'event pagination must advance'); cursor = next;
  }
  const { generated_at, ...report } = await get(`/sessions/${id}/report`);
  assert.ok(events.size > 0);
  assert.equal(report.session_id, id);
  return { detail, events: [...events.values()], report };
}
(async () => {
  const health = await get('/health'); assert.equal(health.checks.db, 'ok');
  if (mode === 'snapshot') {
    const qa = JSON.parse(fs.readFileSync(path.join(output, 'workspace-qa.json'), 'utf8'));
    assert.equal(qa.fixtureCatalog, false, 'require a real catalog QA run');
    assert.equal(qa.failures.length + qa.pageErrors.length, 0);
    const ids = [...new Set(qa.messages.filter(message => message.t === 'ended').map(message => message.session_id))];
    assert.ok(ids.length >= 2, 'consultation and TRACE must both have ended');
    const sessions = await Promise.all(ids.map(session));
    const packs = await get('/packs'); assert.ok(packs.packs.length >= 2);
    fs.writeFileSync(snapshotPath, JSON.stringify({ sessions, packs }, null, 2));
    console.log('Saved real PostgreSQL snapshots:', ids.join(', '));
  } else if (mode === 'verify') {
    const before = JSON.parse(fs.readFileSync(snapshotPath, 'utf8'));
    const after = await Promise.all(before.sessions.map(record => session(record.detail.session_id)));
    assert.deepEqual(after, before.sessions, 'records/events/report must survive restart unchanged');
    assert.deepEqual(await get('/packs'), before.packs, 'published packs must survive restart');
    const history = await get('/sessions?limit=100');
    for (const record of after) assert.ok(history.sessions.some(value => value.session_id === record.detail.session_id), 'history must not rely on browser storage');
    const result = { verified_at: new Date().toISOString(), health, sessions: after.map(record => ({ id: record.detail.session_id, mode: record.detail.mode, events: record.events.length })), identicalAfterRestart: true, packCount: before.packs.packs.length };
    fs.writeFileSync(path.join(output, 'persistence-qa.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } else throw new Error('Usage: node scripts/persistence-qa.cjs snapshot|verify');
})().catch(error => { console.error(error); process.exitCode = 1; });
