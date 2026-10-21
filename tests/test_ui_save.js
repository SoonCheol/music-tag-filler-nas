// Local VM tests: exercise the actual UI handlers without network or music writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('app/static/index.html', 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1]
  .replace(/^loadPreferences\(\);/m, '')
  .replace(/^loadFolders\(\);\s*^pollJobs\(\);/m, '');
const elements = new Map(), checks = [], sent = [], notices = [];
function element() {
  return { value: '', checked: false, hidden: true, style: {}, children: [], listeners: {},
    innerHTML: '', textContent: '', classList: { add() {}, remove() {} },
    setAttribute() {}, focus() {}, appendChild(child) { this.children.push(child); },
    replaceChildren() { this.children = []; },
    addEventListener(name, callback) { this.listeners[name] = callback; }, contains() { return false; } };
}
function $(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); }
for (const field of ['title', 'artist', 'album', 'albumartist', 'track', 'year', 'genre']) {
  const check = element(); check.checked = true; check.dataset = { field }; checks.push(check);
}
$('onlyEmpty').checked = false;
const context = vm.createContext({ console, Set, Map, encodeURIComponent,
  document: { getElementById: $, createElement: element, addEventListener() {},
    querySelectorAll(selector) { return selector === '.chg-check' ? checks : []; } },
  alert: message => notices.push(message), confirm: () => true,
  fetch: async (url, options) => {
    const body = JSON.parse(options.body); sent.push({ url, body });
    if (url.endsWith('/search')) return { ok: true, text: async () => JSON.stringify({
      ...result(body.path), search_status: 'matched', search_errors: [], country: body.country
    }) };
    if (url.startsWith('/api/revert/')) return { ok: true, text: async () => JSON.stringify({
      status: 'restored', exact: true, original: { title: 'Original', artist: 'Singer', revision: 'b'.repeat(64) }
    }) };
    const results = body.paths.map(path => ({ path, status: 'skipped' }));
    return { ok: true, text: async () => JSON.stringify({ saved: 0, skipped: results.length, failed: 0, partial: 0, results }) };
  }, setTimeout() {} });
vm.runInContext(script, context);
function run(source) { return vm.runInContext(source, context); }
function result(path) {
  return { path, original: { title: 'Original', artist: 'Singer', album: 'Album', revision: 'a'.repeat(64) },
    candidates: [{ id: 'first', title: 'First', artist: 'First singer', score: 95 },
      { id: 'second', title: 'Second', artist: 'Second singer', score: 55 }],
    best: null, auto_apply: false };
}
(async () => {
  context.job = { id: 'one', results: [result('visible.mp3'), result('hidden.mp3')] };
  run('adoptJob(job)');
  assert.equal(run('editingResult._selection'), 'none');
  assert.equal($('chg_title').value, 'Original');
  run('applyCandidate(editingResult, editingResult.candidates[1])');
  $('chg_title').value = 'User edited';
  $('chg_title').listeners.input();
  checks.find(check => check.dataset.field === 'artist').checked = false;
  await run('saveCurrent()');
  const request = sent.at(-1).body;
  assert.equal(request.scope, 'selected');
  assert.deepEqual(request.paths, ['visible.mp3']);
  assert.equal(request.items[0].candidate_id, 'second');
  assert.equal(request.items[0].selection, 'edit');
  assert.equal(request.items[0].values.title, 'User edited');
  assert(!request.items[0].fields.includes('artist'));
  run('selectFile(1); selectFile(0)');
  assert.equal($('chg_title').value, 'User edited');
  assert.equal(checks.find(check => check.dataset.field === 'artist').checked, false);
  context.sameJob = { id: 'one', results: [result('visible.mp3'), result('hidden.mp3'), result('new.mp3')] };
  run('adoptJob(sameJob)');
  assert.equal($('chg_title').value, 'User edited');
  $('fileFilter').value = 'visible'; run('applyFilter()');
  await run('saveAll()');
  assert.equal(sent.at(-1).body.scope, 'selected');
  assert.deepEqual(sent.at(-1).body.paths, ['visible.mp3']);
  $('fileFilter').value = ''; run('applyFilter()');
  await run('saveAll()');
  assert.equal(sent.at(-1).body.scope, 'all');
  assert.deepEqual(sent.at(-1).body.paths, ['visible.mp3', 'hidden.mp3', 'new.mp3']);
  run('currentResults[1]._checked=true');
  await run('saveAll()');
  assert.equal(sent.at(-1).body.scope, 'selected');
  assert.deepEqual(sent.at(-1).body.paths, ['hidden.mp3']);
  context.otherJob = { id: 'two', results: [result('other.mp3')] };
  run('adoptJob(otherJob)');
  assert.equal($('chg_title').value, 'Original');
  assert.equal(run('editingResult._selection'), 'none');
  await run('resetChange()');
  assert.equal(sent.at(-1).url, '/api/revert/other.mp3');
  assert.equal(sent.at(-1).body.expected_revision, 'a'.repeat(64));
  assert.equal(run('editingResult._draftRevision'), 'b'.repeat(64));
  $('searchQ').value = '@JP Singer - Song';
  await run('manualSearch()');
  assert.equal(sent.at(-1).body.country, 'JP');
  assert.equal(sent.at(-1).body.query, 'Singer - Song');
  assert.equal(sent.at(-1).body.mode, 'text');
  $('searchQ').value = '@sound';
  await run('manualSearch()');
  assert.equal(sent.at(-1).body.mode, 'sound');
  console.log('PASS: candidate identity, edited values, field mask, drafts across files/polls, exact selected/filter/all scope, job isolation.');
})().catch(error => { console.error(error); process.exitCode = 1; });
