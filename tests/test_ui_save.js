// Local VM tests: exercise the actual UI handlers without network or music writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('app/static/index.html', 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1]
  .replace(/^pollSaveTasks\(\);/m, '')
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
$('onlyEmpty').checked = false;$('coverMax').value=1000;
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
  return { path, file_state: 'auto', original: { title: 'Original', artist: 'Singer', album: 'Album', revision: 'a'.repeat(64) },
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
  assert.equal(request.scope, 'current');
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
  run('currentResults[0]._checked=true');
  $('fileFilter').value='visible';run('applyFilter()');await acceptSave('saveAll()');
  assert.equal(sent.at(-1).body.scope,'all');assert.deepEqual(sent.at(-1).body.paths,['visible.mp3']);
  $('fileFilter').value='';run('applyFilter()');run('currentResults[1]._checked=true');
  await acceptSave('saveSelected()');assert.equal(sent.at(-1).body.scope,'selected');
  assert.deepEqual(sent.at(-1).body.paths,['visible.mp3','hidden.mp3']);
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
  assert.equal($('btnSaveAll').textContent, '작업 전체 저장 (체크 0곡)');
  run('currentResults[1]._checked=true');
  $('fileFilter').value='show';run('applyFilter()');
  assert.equal($('btnSaveAll').textContent, '작업 전체 저장 (체크 1곡)');
  assert.match($('selectedInfo').textContent, /숨김 1곡/);
  run('toggleCheck(0)');assert.equal($('btnSaveAll').textContent, '작업 전체 저장 (체크 2곡)');
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
  assert.equal($('btnSaveAll').textContent,'작업 전체 저장 (체크 2곡)');
  assert.equal($('btnSaveAll').disabled,false);
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
  run('applyCandidate(editingResult,editingResult.candidates[0])');
  assert.match($('candidateFeedback').textContent,/현재 입력값과 같아/);
  assert.equal(sent.length,callsBeforeApply);
  $('onlyEmpty').checked=true;run('applyCandidate(editingResult,editingResult.candidates[0])');
  assert.match($('candidateFeedback').textContent,/빈 태그만 채우기/);
  run('editingResult._draft=originalValues(editingResult);applyCandidate(editingResult,{id:"empty"})');
  assert.match($('candidateFeedback').textContent,/적용할 태그 정보가 없는/);
  assert.equal(run('Object.keys(buttonHelp).length'),7);
  assert.match(run('buttonHelp.btnApplyCandidate'),/실제 파일은 변경하지 않습니다/);
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
    if(mode==='filter'){$('fileFilter').value='show';run('applyFilter()');run('currentResults[0]._checked=true');}
    if(mode==='all')run('toggleSelectAll(true)');
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
  // Preview only reads drafts: all request counts and save payloads stay unchanged.
  $('fileFilter').value='';$('onlyEmpty').checked=false;run('toggleAllChange(true);adoptJob(previewJob)');
  const previewCalls=sent.length;
  run('applyCandidate(editingResult,editingResult.candidates[0])');
  assert.equal($('cur_title').textContent,'Original');
  const draftPayload=run('JSON.stringify(saveItem(editingResult))');
  run('toggleTagPreview()');
  assert.equal($('btnApplyCandidate').textContent,'미리보기 취소');
  assert.equal($('cur_title').textContent,'First');assert.equal($('cur_title').style.color,'#c62828');
  assert.equal($('tagPreviewLabel').hidden,false);
  assert.equal(run('JSON.stringify(saveItem(editingResult))'),draftPayload);
  $('chg_title').value='Manual draft';$('chg_title').listeners.input();
  assert.equal($('cur_title').textContent,'Manual draft');
  const titleCheck=checks.find(c=>c.dataset.field==='title');titleCheck.checked=false;titleCheck.listeners.change();
  assert.equal($('cur_title').textContent,'Original');assert.equal($('cur_title').style.color,'');
  titleCheck.checked=true;titleCheck.listeners.change();
  $('onlyEmpty').checked=true;run('updateSavePreview()');assert.equal($('cur_title').textContent,'Original');
  $('onlyEmpty').checked=false;run('updateSavePreview()');
  run('toggleTagPreview()');assert.equal($('cur_title').textContent,'Original');
  assert.equal($('chg_title').value,'Manual draft');assert.equal($('tagPreviewLabel').hidden,true);
  run('editingResult._coverId="local-cover";editingResult.original.has_cover=true');
  $('onlyEmpty').checked=true;run('toggleTagPreview()');
  assert(!/uploaded-cover/.test($('currentCover').innerHTML));
  $('onlyEmpty').checked=false;run('updateSavePreview()');
  assert.match($('currentCover').innerHTML,/uploaded-cover\/local-cover/);
  run('toggleTagPreview()');assert(!/uploaded-cover/.test($('currentCover').innerHTML));
  assert.equal(sent.length,previewCalls);
  run('toggleTagPreview();selectFile(1)');assert.equal($('btnApplyCandidate').textContent,'미리보기');
  assert.equal($('tagPreviewLabel').hidden,true);
  assert(!html.includes('>선택 적용</button>'));assert(!html.includes('onclick="applySelectedCandidate()"'));
  const currentSection=html.slice(html.indexOf('<h4>현재 태그 정보'),html.indexOf('<h4><label>'));
  assert(!currentSection.includes('<input'));assert(!currentSection.includes('저장 전'));
  // Regression: selecting with fill-empty on must retain candidate values for later overwrite.
  $('fileFilter').value='';$('onlyEmpty').checked=true;run('adoptJob(previewJob)');
  run('applyCandidate(editingResult,editingResult.candidates[0]);toggleTagPreview()');
  assert.equal($('chg_title').value,'First');assert.equal($('cur_title').textContent,'Original');
  $('onlyEmpty').checked=false;run('updateSavePreview()');assert.equal($('cur_title').textContent,'First');
  $('chg_title').value='My manual title';$('chg_title').listeners.input();
  $('onlyEmpty').checked=true;run('updateSavePreview()');assert.equal($('cur_title').textContent,'Original');
  $('onlyEmpty').checked=false;run('updateSavePreview()');assert.equal($('cur_title').textContent,'My manual title');
  $('coverMax').value=320;await acceptSave('saveCurrent()');assert.equal(sent.at(-1).body.cover_max_px,320);
  $('searchCountry').value='TW';$('searchQ').value='Singer - Song';await run('manualSearch()');
  assert.equal(sent.at(-1).body.country,'TW');
  // Switching display preference changes candidate-derived values, never manually edited fields.
  run('applyCandidate(editingResult,{id:"first",title:"First",artist:"原文",artist_latin:"Latin",albumartist:"原文",album_artist_latin:"Latin album"})');
  run('editingResult.candidates[0].artist="原文";editingResult.candidates[0].artist_latin="Latin"');
  $('artistPreference').value='latin';run('refreshCandidatePreference();updateSavePreview()');assert.equal($('chg_artist').value,'Latin');
  $('chg_artist').value='My artist';$('chg_artist').listeners.input();
  $('artistPreference').value='original';run('refreshCandidatePreference();updateSavePreview()');assert.equal($('chg_artist').value,'My artist');
  // Automatic candidates use the same overwrite option as manual candidates.
  context.autoJob={id:'auto',results:[{...result('auto.mp3'),auto_apply:true,best:{id:'first',title:'First',artist:'Singer'}}]};
  run('adoptJob(autoJob);toggleTagPreview()');assert.equal($('cur_title').textContent,'First');
  $('onlyEmpty').checked=true;run('updateSavePreview()');assert.equal($('cur_title').textContent,'Original');
  $('onlyEmpty').checked=false;
  context.blankAuto={id:'blank-auto',results:[{path:'blank.mp3',original:{revision:'a'.repeat(64)},auto_apply:true,
    best:{id:'latin-auto',title:'Song',artist:'原文',artist_latin:'Latin'},
    candidates:[{id:'latin-auto',title:'Song',artist:'原文',artist_latin:'Latin'}]}]};
  $('artistPreference').value='latin';run('adoptJob(blankAuto);toggleTagPreview()');
  assert.equal($('cur_artist').textContent,'Latin');
  $('artistPreference').value='original';run('refreshCandidatePreference();updateSavePreview()');
  assert.equal($('cur_artist').textContent,'原文');
  context.bigbang={id:'bigbang',results:[{path:'song.mp3',original:{artist:'빅뱅',title:'Song',revision:'a'.repeat(64)},
    auto_apply:true,best:{id:'band',artist:'BIGBANG',title:'Song'},candidates:[{id:'band',artist:'BIGBANG',title:'Song'}]}]};
  for(const automatic of [true,false]){
    run('adoptJob(bigbang)');
    if(!automatic)run('applyCandidate(editingResult,editingResult.candidates[0])');
    if(run('previewPath')!==run('editingResult.path'))run('toggleTagPreview()');
    const artistCheck=checks.find(c=>c.dataset.field==='artist');
    for(const emptyOnly of [true,false])for(const checked of [true,false]){
      $('onlyEmpty').checked=emptyOnly;artistCheck.checked=checked;run('captureCurrent();updateSavePreview()');
      assert.equal($('cur_artist').textContent,!emptyOnly&&checked?'BIGBANG':'빅뱅');
      assert.equal($('cur_artist').style.color,!emptyOnly&&checked?'#c62828':'');
    }
    artistCheck.checked=true;$('onlyEmpty').checked=false;run('captureCurrent()');
    $('chg_artist').value='My manual band';$('chg_artist').listeners.input();
    assert.equal($('cur_artist').textContent,'My manual band');
    $('onlyEmpty').checked=true;run('updateSavePreview()');
    $('onlyEmpty').checked=false;run('updateSavePreview()');assert.equal($('cur_artist').textContent,'My manual band');
  }
  run('reportSave({saved:1,skipped:2,failed:0,partial:0,unchanged:1,unselected:1,results:[]})');
  assert.match($('saveResultCounts').innerHTML,/변경 없음: 1/);assert.match($('saveResultCounts').innerHTML,/미선택: 1/);
  context.statesJob={id:'states',results:[result('auto1.mp3'),{...result('review.mp3'),file_state:'review'},
    {...result('saved.mp3'),file_state:'saved'},result('auto2.mp3')]};
  $('fileFilter').value='';run('adoptJob(statesJob);currentResults.forEach(r=>r._checked=true);renderFileList()');
  assert.deepEqual(JSON.parse(run('JSON.stringify(currentResults.map(r=>!!r._checked))')),[true,false,false,true]);
  assert.equal($('fileBody').children.slice(-4)[1].innerHTML.includes('disabled'),true);
  assert.equal($('fileBody').children.slice(-4)[2].innerHTML.includes('disabled'),true);
  $('fileFilter').value='auto1';run('applyFilter()');
  await acceptSave('saveSelected()');assert.deepEqual(sent.at(-1).body.paths,['auto1.mp3','auto2.mp3']);
  assert.deepEqual(sent.at(-1).body.checked_paths,['auto1.mp3','auto2.mp3']);
  run('toggleSelectAll(false)');assert.equal($('btnSaveAll').disabled,true);assert.equal($('btnSaveSelected').disabled,true);
  $('fileFilter').value='';run('applyFilter();selectFile(1)');
  $('chg_title').value='Preserved review draft';$('chg_title').listeners.input();
  const moveCancel=run('requestSelectFile(2)');assert.equal($('actionAccept').textContent,'버리고 이동');
  run('resolveAction(false)');await moveCancel;assert.equal(run('editingResult.path'),'review.mp3');
  const moveKeep=run('requestSelectFile(2)');run('resolveAction(true)');await moveKeep;
  assert.equal(run('editingResult.path'),'saved.mp3');assert.equal($('btnSaveCurrent').disabled,false);
  await run('requestSelectFile(1)');assert.equal($('chg_title').value,'Original');
  assert.equal(run('fileState(editingResult)'),'review'); // Editing never promotes status.
  console.log('PASS: candidate identity, edited values, field mask, drafts across files/polls, exact selected/filter/all scope, job isolation.');
})().catch(error => { console.error(error); process.exitCode = 1; });
