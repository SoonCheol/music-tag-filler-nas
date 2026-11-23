// Local VM tests: exercise the actual UI handlers without network or music writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
// Load each classic script in the same order and scope as the page.
const pageHtml = fs.readFileSync('app/static/index.html', 'utf8');
const scriptPaths = [...pageHtml.matchAll(/<script src="(\/static\/js\/[^" ]+)"[^>]*><\/script>/g)].map(m => 'app' + m[1].split('?')[0]);
assert.equal(scriptPaths.length, 6);
assert.equal(scriptPaths.at(-1), 'app/static/js/app.js');
assert.equal(new Set(scriptPaths).size, scriptPaths.length);
assert(!/<script[^>]+(?:async|defer|type=)/.test(pageHtml));
// Feature scripts must load without DOM access or initialized shared state.
scriptPaths.slice(0, -1).forEach(p => vm.runInNewContext(fs.readFileSync(p, 'utf8'), {}, {filename:p}));
const uiScripts = scriptPaths.map(p => ({path:p, source:fs.readFileSync(p, 'utf8')
  .replace(/^(?:loadPreferences|loadFolders|pollJobs|pollSaveTasks)\(\);/gm, '')}));
const script = uiScripts.map(s => s.source).join('\n');
// Preserve the existing source assertions across the split assets.
const html = pageHtml
  .replace('<link rel="stylesheet" href="/static/css/style.css">', () => '<style>' + fs.readFileSync('app/static/css/style.css', 'utf8') + '</style>')
  .replace(/<script src="(\/static\/js\/[^" ]+)"[^>]*><\/script>/g, (_,p) => '<script>' + fs.readFileSync('app' + p.split('?')[0], 'utf8') + '</script>');
const elements = new Map(), checks = [], sent = [], notices = [];
function element() {
  return { value: '', checked: false, hidden: true, style: {setProperty(k,v){this[k]=v;}}, children: [], listeners: {},
    showModal() { this.open=true; }, close() { this.open=false; }, innerHTML: '', textContent: '', classList: { add() {}, remove() {} },
    setAttribute() {}, focus() {}, appendChild(child) { this.children.push(child); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(name, callback) { this.listeners[name] = callback; }, contains() { return false; } };
}
function $(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); }
for (const field of ['title', 'artist', 'album', 'albumartist', 'track', 'year', 'genre']) {
  const check = element(); check.checked = true; check.dataset = { field }; checks.push(check);
}
$('saveCover').checked=true;$('saveLyrics').checked=true;
$('onlyEmpty').checked = false;$('coverMax').value=1000;
const context = vm.createContext({ console, Set, Map, encodeURIComponent, clearTimeout, AbortController, performance: {now: () => 0},
  document: { getElementById: $, createElement: element, addEventListener() {},
    querySelectorAll(selector) { return selector === '.chg-check' ? checks : []; } },
  alert: message => notices.push(message), confirm: () => true,
  fetch: async (url, options) => {
    if(url.endsWith('/candidate-lyrics'))return {ok:true,text:async()=>JSON.stringify({status:'not_found',lyrics:''})};
    if(url.startsWith('/api/lyrics/'))return {ok:true,text:async()=>JSON.stringify({lyrics:''})};
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
uiScripts.forEach(s => vm.runInContext(s.source, context, {filename:s.path}));
function run(source) { return vm.runInContext(source, context); }
async function acceptSave(source) {
  const pending=run(source);assert.equal($('saveConfirmDialog').open,true);
  assert.equal($('saveConfirmAccept').textContent,'저장 실행');
  assert.equal($('saveConfirmCancel').textContent,'취소');
  run('resolveSaveConfirm(true)');await pending;
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
  checks.find(check => check.dataset.field === 'artist').checked = false;checks.find(check => check.dataset.field === 'artist').listeners.change();
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
  const restoreConfirmation=run('resetChange()');run('resolveAction(true)');await restoreConfirmation;
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
  $('onlyEmpty').checked=false;run('updateSavePreview()');
  checks.find(c=>c.dataset.field==='title').checked=false;checks.find(c=>c.dataset.field==='title').listeners.change();run('captureCurrent();updateSavePreview()');
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
  assert.equal($('candidateFeedback').hidden,true);
  assert.equal($('candidateFeedback').hidden,true);
  assert.match($('chg_title').style.boxShadow,/2px/);
  run('applyCandidate(editingResult,editingResult.candidates[0])');
  assert.equal($('candidateFeedback').hidden,true);
  assert.equal(sent.length,callsBeforeApply);
  $('onlyEmpty').checked=true;run('applyCandidate(editingResult,editingResult.candidates[0])');
  assert.equal($('candidateFeedback').hidden,true);
  run('editingResult._draft=originalValues(editingResult);applyCandidate(editingResult,{id:"empty"})');
  assert.equal($('candidateFeedback').hidden,true);
  assert.equal(run('Object.keys(buttonHelp).length'),7);
  assert.match(run('buttonHelp.btnApplyCandidate'),/실제 파일은 변경하지 않습니다/);
  assert.match(run('buttonHelp.btnRestore'),/실제 음악 파일/);
  for(const id of run('Object.keys(buttonHelp)')){
    assert.equal(typeof $(id).listeners.mouseenter,'function');
    assert.equal(typeof $(id).listeners.focus,'function');
    assert.equal(typeof $(id).listeners.mouseleave,'function');
  }
  $('onlyEmpty').checked=false;run('updateSavePreview()');
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
    assert.match($('saveConfirmBody').innerHTML,mode==='current'?/저장 항목/:/파일명 자동 변경/);
    await run(source);assert.equal(sent.length,before); // No duplicate submission.
    run('resolveSaveConfirm(false)');await pending;
    assert.equal(sent.length,before);assert.equal(run('saving'),false);
    const escaped=run(source);run('resolveSaveConfirm(false)');await escaped;
    assert.equal(sent.length,before);assert.equal(run('saving'),false);
  }
  context.mismatchJob={id:'mismatch',results:[result('mismatch.mp3')]};run('adoptJob(mismatchJob);toggleAllChange(true)');
  const mismatchCases=[['Final title','Singer',['제목']],['Original','New singer',['가수']],['Final title','New singer',['제목','가수']]];
  for(const [title,artist,labels] of mismatchCases){
    $('chg_title').value=title;$('chg_title').listeners.input();$('chg_artist').value=artist;$('chg_artist').listeners.input();
    run("editingResult._lyricsSearch={status:'found',manual:true,lyrics_id:'manual-token',lyrics:'verified',queryKey:JSON.stringify(['Original','Singer']),query_title:'Original',query_artist:'Singer'}");
    assert.deepEqual(Array.from(run('manualMismatch(editingResult).map(x=>x.label)')),labels);
  }
  const mismatchBefore=sent.length,mismatchSave=run('saveCurrent()');assert.equal($('saveConfirmAccept').textContent,'확인 후 저장');
  assert.match($('saveConfirmBody').innerHTML,/가사 검색 정보 불일치/);assert.match($('saveConfirmBody').innerHTML,/저장할 태그/);
  run('resolveSaveConfirm(false)');await mismatchSave;assert.equal(sent.length,mismatchBefore);assert.equal($('chg_title').value,'Final title');assert.equal($('chg_artist').value,'New singer');
  const approved=run('saveCurrent()');run('resolveSaveConfirm(true)');await approved;
  assert.equal(sent.at(-1).body.items[0].approve_manual_lyrics_mismatch,true);assert.equal(sent.at(-1).body.rename,false);
  assert.equal(sent.at(-1).body.items[0].values.title,'Final title');assert.equal(sent.at(-1).body.items[0].values.artist,'New singer');
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
  const currentSection=html.slice(html.indexOf('<h4>현재 태그 정보'),html.indexOf('<h4>변경할 태그 정보'));
  assert(!currentSection.includes('<input'));assert(!currentSection.includes('저장 전'));
  // Regression: selecting with fill-empty on must retain candidate values for later overwrite.
  $('fileFilter').value='';$('onlyEmpty').checked=true;run('adoptJob(previewJob)');
  run('applyCandidate(editingResult,editingResult.candidates[0]);toggleTagPreview()');
  assert.equal($('chg_title').value,'Original');assert.equal($('cur_title').textContent,'Original');
  $('onlyEmpty').checked=false;run('applyCandidate(editingResult,editingResult.candidates[0]);updateSavePreview()');assert.equal($('cur_title').textContent,'First');
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
      $('onlyEmpty').checked=emptyOnly;run('updateSavePreview()');if(!artistCheck.disabled){artistCheck.checked=checked;artistCheck.listeners.change();}run('captureCurrent();updateSavePreview()');
      assert.equal($('cur_artist').textContent,!emptyOnly&&checked?'BIGBANG':'빅뱅');
      assert.equal($('cur_artist').style.color,!emptyOnly&&checked?'#c62828':'');
    }
    $('onlyEmpty').checked=false;run('updateSavePreview()');artistCheck.checked=true;artistCheck.listeners.change();run('captureCurrent()');
    $('chg_artist').value='My manual band';$('chg_artist').listeners.input();
    assert.equal($('cur_artist').textContent,'My manual band');
    $('onlyEmpty').checked=true;run('updateSavePreview()');
    $('onlyEmpty').checked=false;run('updateSavePreview()');assert.equal($('cur_artist').textContent,'My manual band');
  }
  run("reportSave({saved:1,skipped:2,failed:0,partial:0,unchanged:1,unselected:1,results:[]},'selected',[],new Map())");
  assert.match($('saveResultCounts').innerHTML,/변경 없음/);assert.match($('saveResultCounts').innerHTML,/<strong>1<\/strong>/);
  context.statesJob={id:'states',results:[result('auto1.mp3'),{...result('review.mp3'),file_state:'review'},
    {...result('saved.mp3'),file_state:'saved'},result('auto2.mp3')]};
  $('fileFilter').value='';run('adoptJob(statesJob);currentResults.forEach(r=>r._checked=true);renderFileList()');
  assert.deepEqual(JSON.parse(run('JSON.stringify(currentResults.map(r=>!!r._checked))')),[true,false,false,true]);
  assert.equal($('fileBody').children.filter(row=>row.className!=='file-empty')[1].innerHTML.includes('disabled'),true);
  assert.equal($('fileBody').children.filter(row=>row.className!=='file-empty')[2].innerHTML.includes('disabled'),true);
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
  // Direct lyrics are independent of search tokens and survive redraws/polls.
  context.directJob={id:'direct',results:[result('direct.mp3')]};
  const lyricMarkup=pageHtml.match(/<textarea\b[^>]*id="changeLyrics"[^>]*>/)[0];
  assert(!/\s(?:readonly|disabled)(?:\s|=|>)/i.test(lyricMarkup));
  assert(scriptPaths.includes('app/static/js/lyrics.js'));
  assert(scriptPaths.includes('app/static/js/app.js'));
  run('adoptJob(directJob)');$('onlyEmpty').checked=false;run('updateSavePreview()');
  run("editingResult.original.revision='';saving=true;updateSavePreview()");
  assert.equal($('changeLyrics').readOnly,false);
  run("editingResult.original.revision='a'.repeat(64);saving=false;updateSavePreview()");
  assert.equal($('changeLyrics').readOnly,false);
  const directText='직접 입력한 가사\nPasted second line';
  $('changeLyrics').value=directText;$('changeLyrics').listeners.input();
  run("editingResult._lyricsSearch={status:'not_found'};updateSavePreview()");
  assert.equal($('changeLyrics').value,directText);
  context.directPoll={id:'direct',results:[result('direct.mp3')]};
  run("editingResult._lyricsSearch={status:'searching'};updateSavePreview();adoptJob(directPoll)");
  assert.equal($('changeLyrics').value,directText);
  assert.equal(run('saveItem(editingResult).lyrics_text'),directText);
  assert.equal(run('saveItem(editingResult).lyrics_id'),null);
  $('saveLyrics').checked=false;run('captureCurrent();updateSavePreview()');
  assert.equal(run('saveItem(editingResult).lyrics_text'),null);
  assert.match($('manualLyricsStatus').textContent,/체크가 꺼져/);
  assert.equal($('changeLyrics').value,directText);
  $('saveLyrics').checked=true;run('captureCurrent();editingResult.original.has_lyrics=true');
  $('onlyEmpty').checked=true;run('updateSavePreview()');
  assert.equal($('changeLyrics').readOnly,false);
  assert.equal(run('saveItem(editingResult).lyrics_text'),null);
  assert.match($('manualLyricsStatus').textContent,/기존 가사를 보호/);
  $('onlyEmpty').checked=false;run('updateSavePreview()');
  await acceptSave('saveCurrent()');
  assert.equal(sent.at(-1).body.items[0].lyrics_text,directText);
  assert.equal(sent.at(-1).body.save_lyrics,true);
  // Searched lyrics remain editable and editing does not mutate search provenance.
  context.searchedJob={id:'searched',results:[result('searched.mp3')]};run('adoptJob(searchedJob)');
  run("editingResult._lyricsSearch={status:'found',lyrics:'Search result',lyrics_id:'token',queryKey:lyricQueryKey(editingResult)};updateSavePreview()");
  assert.equal($('changeLyrics').readOnly,false);
  $('changeLyrics').value='Edited search result';$('changeLyrics').listeners.input();
  assert.equal(run('saveItem(editingResult).lyrics_text'),'Edited search result');
  assert.equal(run('editingResult._lyricsSearch.lyrics'),'Search result');
  $('changeLyrics').value='';$('changeLyrics').listeners.input();
  assert.equal(run('saveItem(editingResult).lyrics_text'),null);
  assert.match($('manualLyricsStatus').textContent,/빈 가사는 저장하지/);
  console.log('PASS: save UI, direct/searched lyric edits, draft preservation, checkbox/protection and save payload.');
})().catch(error => { console.error(error); process.exitCode = 1; });
