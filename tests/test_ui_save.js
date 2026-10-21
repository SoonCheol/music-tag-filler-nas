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
    showModal() { this.open=true; }, close() { this.open=false; }, innerHTML: '', textContent: '', classList: { add() {}, remove() {} },
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
async function acceptSave(source) {
  const pending=run(source);assert.equal($('actionDialog').open,true);
  assert.equal($('actionAccept').textContent,'저장 실행');
  assert.equal($('actionCancel').textContent,'취소');
  run('resolveAction(true)');await pending;
}
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
  await acceptSave('saveCurrent()');
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
  await acceptSave('saveAll()');
  assert.equal(sent.at(-1).body.scope, 'selected');
  assert.deepEqual(sent.at(-1).body.paths, ['visible.mp3']);
  $('fileFilter').value = ''; run('applyFilter()');
  await acceptSave('saveAll()');
  assert.equal(sent.at(-1).body.scope, 'all');
  assert.deepEqual(sent.at(-1).body.paths, ['visible.mp3', 'hidden.mp3', 'new.mp3']);
  run('currentResults[1]._checked=true');
  await acceptSave('saveAll()');
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
  // UI safety preview: the button and request must use the same target.
  context.previewJob = { id: 'preview', results: [result('show.mp3'), result('hide.mp3')] };
  run('adoptJob(previewJob)');
  assert.equal($('btnSaveAll').textContent, '작업 전체 2곡 저장');
  run('currentResults[1]._checked=true');
  $('fileFilter').value='show';run('applyFilter()');
  assert.equal($('btnSaveAll').textContent, '필터 결과 1곡 저장');
  assert.match($('selectedInfo').textContent, /숨김 1곡/);
  run('toggleCheck(0)');assert.equal($('btnSaveAll').textContent, '체크한 1곡 저장');
  $('chg_title').value='New title';$('chg_title').listeners.input();
  assert.match($('changeSummary').textContent, /제목/);
  $('onlyEmpty').checked=true;run('updateSavePreview()');
  assert.match($('changeSummary').textContent, /텍스트 변경 없음/);
  $('onlyEmpty').checked=false;
  checks.find(c=>c.dataset.field==='title').checked=false;run('captureCurrent();updateSavePreview()');
  assert.match($('changeSummary').textContent, /텍스트 변경 없음/);
  run('editingResult._coverId="temporary-cover"; updateSavePreview()');
  assert.match($('changeSummary').textContent, /커버 적용 시도/);
  const callsBeforeDiscard=sent.length;
  const discard=run('discardDraft()');run('resolveAction(true)');await discard;
  assert.equal(sent.length,callsBeforeDiscard); // Cancel never calls restore or save.
  assert.equal($('chg_title').value,'Original');
  assert.equal(run('editingResult._coverId'),null);
  assert.equal(run('editingResult._selection'),'none');
  $('fileFilter').value='missing';run('applyFilter()');
  assert.equal($('btnSaveAll').textContent,'필터 결과 0곡 저장');
  assert.equal($('btnSaveAll').disabled,true);
  assert.equal($('btnRestore').disabled,true);
  assert(html.includes('>최초 원본 복원</button>'));
  assert(html.includes('>편집 취소</button>'));
  $('fileFilter').value='';run('adoptJob(previewJob)');
  $('onlyEmpty').checked=false;
  const callsBeforeApply=sent.length;
  run('applyCandidate(editingResult,editingResult.candidates[0])');
  assert.equal($('chg_title').value,'First');
  assert.match($('candidateFeedback').textContent,/후보 정보가 적용되었습니다/);
  assert.match($('candidateFeedback').textContent,/파일 저장 전/);
  assert.match($('chg_title').style.boxShadow,/2px/);
  run('applySelectedCandidate()');
  assert.match($('candidateFeedback').textContent,/현재 입력값과 같아/);
  assert.equal(sent.length,callsBeforeApply);
  $('onlyEmpty').checked=true;run('applySelectedCandidate()');
  assert.match($('candidateFeedback').textContent,/빈 태그만 채우기/);
  run('editingResult._candidateId=null;applySelectedCandidate()');
  assert.match($('candidateFeedback').textContent,/적용할 후보가 없습니다/);
  run('editingResult._draft=originalValues(editingResult);applyCandidate(editingResult,{id:"empty"})');
  assert.match($('candidateFeedback').textContent,/적용할 태그 정보가 없는/);
  assert.equal(run('Object.keys(buttonHelp).length'),6);
  assert.match(run('buttonHelp.btnApplyCandidate'),/아직 저장하지 않습니다/);
  assert.match(run('buttonHelp.btnRestore'),/실제 음악 파일/);
  for(const id of run('Object.keys(buttonHelp)')){
    assert.equal(typeof $(id).listeners.mouseenter,'function');
    assert.equal(typeof $(id).listeners.focus,'function');
    assert.equal(typeof $(id).listeners.mouseleave,'function');
  }
  // Every save entry point must wait for confirmation; cancel/Escape sends nothing.
  for(const mode of ['current','all','filter','checked']){
    $('fileFilter').value='';run('adoptJob(previewJob)');
    run('currentResults.forEach(r=>r._checked=false)');
    if(mode==='filter'){$('fileFilter').value='show';run('applyFilter()');}
    if(mode==='checked')run('currentResults[0]._checked=true');
    const source=mode==='current'?'saveCurrent()':'saveAll()';
    const before=sent.length,pending=run(source);
    assert.equal(sent.length,before);assert.equal(run('saving'),true);
    assert.match($('actionMessage').textContent,/빈칸만:.*파일명 변경:/);
    await run(source);assert.equal(sent.length,before); // No duplicate submission.
    run('resolveAction(false)');await pending;
    assert.equal(sent.length,before);assert.equal(run('saving'),false);
    const escaped=run(source);$('actionDialog').listeners.cancel({preventDefault(){}});await escaped;
    assert.equal(sent.length,before);assert.equal(run('saving'),false);
  }
  const saveHandler=script.slice(script.indexOf('async function submitSave'),script.indexOf('async function saveCurrent'));
  assert(!/\bconfirm\(/.test(saveHandler));
  console.log('PASS: candidate identity, edited values, field mask, drafts across files/polls, exact selected/filter/all scope, job isolation.');
})().catch(error => { console.error(error); process.exitCode = 1; });
