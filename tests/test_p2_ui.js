// Actual page handlers in an isolated DOM model. No browser/NAS/music mutations.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
// Load each classic script in the same order and scope as the page.
const pageHtml = fs.readFileSync('app/static/index.html', 'utf8');
const scriptPaths = [...pageHtml.matchAll(/<script src="(\/static\/js\/[^" ]+)"[^>]*><\/script>/g)].map(m => 'app' + m[1].split('?')[0]);
assert.equal(scriptPaths.length, 7);
assert.equal(scriptPaths.at(-2), 'app/static/js/app.js');
assert.equal(scriptPaths.at(-1), 'app/static/js/nas-updater.js');
assert.equal(new Set(scriptPaths).size, scriptPaths.length);
assert(!/<script[^>]+(?:async|defer|type=)/.test(pageHtml));
// Feature scripts must load without DOM access or initialized shared state.
scriptPaths.slice(0, -2).forEach(p => vm.runInNewContext(fs.readFileSync(p, 'utf8'), {}, {filename:p}));
const uiScripts = scriptPaths.map(p => ({path:p, source:fs.readFileSync(p, 'utf8')
  .replace(/^(?:loadPreferences|loadFolders|pollJobs|pollSaveTasks)\(\);/gm, '')}));
const script = uiScripts.map(s => s.source).join('\n');
// Preserve the existing source assertions across the split assets.
const html = pageHtml
  .replace('<link rel="stylesheet" href="/static/css/style.css">', () => '<style>' + fs.readFileSync('app/static/css/style.css', 'utf8') + '</style>')
  .replace(/<script src="(\/static\/js\/[^" ]+)"[^>]*><\/script>/g, (_,p) => '<script>' + fs.readFileSync('app' + p.split('?')[0], 'utf8') + '</script>');
const memory = new Map();
function harness() {
  const elements = new Map(), checks = [], calls = [], documentEvents = {};
  function element() {return {value:'',checked:false,hidden:true,style:{setProperty(k,v){this[k]=v;}},children:[],listeners:{},attributes:{},dataset:{},scrollTop:0,_innerHTML:'',
    showModal(){this.open=true;},close(){this.open=false;},reportValidity(){return this.valid!==false;},
    get innerHTML(){return this._innerHTML;},set innerHTML(value){this._innerHTML=value;if(value==='')this.children=[];},textContent:'',classList:{add(){},remove(){}},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];if(k==='src')this.src='';},focus(){},
    appendChild(child){child.parent=this;this.children.push(child);},replaceChildren(...children){this.children.forEach(c=>c.parent=null);this.children=[];children.forEach(c=>this.appendChild(c));},
    addEventListener(name,fn){this.listeners[name]=fn;},contains(target){return target===this||this.children.some(c=>c.contains(target));}};}
  function $(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}
  for(const field of ['title','artist','album','albumartist','track','year','genre']){const check=element();check.checked=true;check.dataset={field};checks.push(check);}
  const context=vm.createContext({console,Set,Map,Number,AbortController,URL,clearTimeout,performance:{now:()=>0},requestAnimationFrame:fn=>fn(),encodeURIComponent,localStorage:{getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v)},
    document:{getElementById:$,createElement:element,addEventListener:(k,f)=>documentEvents[k]=f,querySelectorAll:s=>s==='.chg-check'?checks:[]},
    alert(){},confirm:()=>true,setTimeout(){},fetch:async(url,options={})=>{let body=options.body;
      if(typeof body==='string')body=JSON.parse(body);calls.push({url,body,method:options.method});
      let value=[];
      if(url.startsWith('/api/lyrics/'))value={lyrics:context.storedLyricText||''};
      else if(url.endsWith('/lyrics-search'))value=context.lyricResponse||{status:'not_found',searched:true,lyrics:'',lyrics_id:'no-result'};
      else if(url.startsWith('/api/path-changes'))value=context.pathChanges||{changes:[]};
      else if(url.endsWith('/rename'))value=context.renameResponse||{};
      else if(url==='/api/jobs'||url==='/api/jobs?summary=true')value=context.jobsResponse||[];
      else if(url.endsWith('/cover-upload'))value={cover_id:'cover-token'};
      else if(url==='/api/preferences')value=options.method?body:context.preferencesResponse||{country:'JP',recurse:false,only_empty:true,fill_lyrics:true,rename:true,include_ids:true,artist_name_preference:'latin',cover_max_px:500};
      else if(url==='/api/scan')value={job_id:'scan'};
      else if(url.endsWith('/save'))value=context.saveResponse||{saved:0,skipped:body.paths.length,failed:0,partial:0,results:body.paths.map(path=>({path,status:'skipped'}))};
      return {ok:true,text:async()=>JSON.stringify(value)};
    }});
  Object.assign($('previewAudio'),{paused:true,ended:false,currentTime:0,loads:0,plays:0,canPlayType:()=> 'probably',
    load(){this.loads++;this.currentTime=0;this.currentSrc=this.src;this.ended=false;},
    pause(){this.paused=true;this.listeners.pause?.();},
    async play(){this.plays++;this.paused=false;this.currentSrc=this.src;this.listeners.playing?.();}});
  $('saveCover').checked=true;$('saveLyrics').checked=true;
  uiScripts.forEach(s => vm.runInContext(s.source, context, {filename:s.path}));
  return {$,calls,context,documentEvents,run:code=>vm.runInContext(code,context)};
}
function click(button,h){let stopped=false;const event={target:button,stopPropagation(){stopped=true;}};button.onclick(event);if(!stopped)h.documentEvents.click(event);return stopped;}
function row(h,title){return h.$('folderOptions').children.find(r=>r.children.at(-1).title===title);}
(async()=>{
  const playback=harness();
  playback.context.audioJob={id:'preview',results:[{path:'one.mp3',file_state:'auto',original:{title:'One',revision:'a'.repeat(64)}},{path:'two.mp3',file_state:'review',original:{title:'Two',revision:'a'.repeat(64)}}]};
  playback.run('adoptJob(audioJob)');const audio=playback.$('previewAudio');
  playback.$('fileListScroller').scrollTop=130;
  playback.run('updateAudioButtons()');assert.equal(playback.$('headerAudio').disabled,true);await playback.run('toggleHeaderAudio()');assert.equal(audio.loads,0);
  await playback.run('toggleAudio(0)');assert.equal(audio.paused,false);assert.equal(playback.run('audioPlaying'),true);assert.equal(playback.run('editingResult.path'),'one.mp3');
  audio.currentTime=4.2;await playback.run('toggleAudio(0)');assert.equal(audio.paused,true);assert.equal(audio.currentTime,4.2);
  await playback.run('toggleAudio(0)');assert.equal(audio.paused,false);assert.equal(audio.currentTime,4.2);assert.equal(audio.loads,1);
  assert.equal(playback.$('headerAudio').textContent,'⏸');assert.equal(playback.$('headerAudio').disabled,false);
  const sortBefore=playback.run('fileSortColumn');
  playback.run('filteredResults=[audioJob.results[1]]');
  await playback.run('toggleHeaderAudio()');assert.equal(audio.paused,true);assert.equal(audio.currentTime,4.2);assert.equal(playback.$('headerAudio').textContent,'▶');
  await playback.run('toggleHeaderAudio()');assert.equal(audio.paused,false);assert.equal(audio.currentTime,4.2);assert.equal(audio.loads,1);
  assert.equal(playback.run('editingResult.path'),'one.mp3');assert.equal(playback.run('fileSortColumn'),sortBefore);assert.equal(playback.$('fileListScroller').scrollTop,130);
  assert.ok(playback.run("audioButton('one.mp3',0)").includes('⏸'));
  playback.run('filteredResults=audioJob.results');
  playback.run('selectFile(1)');playback.$('chg_title').value='Only editor changed';playback.$('chg_title').listeners.input();
  assert.equal(audio.paused,false);assert.equal(playback.run('playingPath'),'one.mp3');assert.equal(playback.$('fileListScroller').scrollTop,130);
  await playback.run('toggleAudio(1)');assert.equal(playback.run('playingPath'),'two.mp3');assert.equal(audio.currentTime,0);assert.equal(audio.loads,2);
  audio.listeners.ended();assert.equal(playback.run('audioPlaying'),false);assert.equal(playback.run('playingPath'),null);
  await playback.run('toggleAudio(0)');audio.error={code:4};audio.listeners.error();assert.equal(playback.run('audioPlaying'),false);assert.equal(playback.run("canPreviewAudio('one.mp3')"),false);
  audio.canPlayType=()=>'';assert.equal(playback.run("canPreviewAudio('two.mp3')"),false);
  assert.ok(html.includes('event.stopPropagation();toggleAudio('));assert.ok(html.includes('width:24px;height:24px;'));
  assert.ok(html.includes('id="previewAudio" preload="none" hidden'));
  assert.ok(html.includes('event.stopPropagation();toggleHeaderAudio()'));
  assert.equal((html.match(/<audio /g)||[]).length,1);
  assert.ok(html.includes('NAS v2.0.0'));
  assert.ok(html.includes('id="appVersion"'));
  assert.ok(!html.includes('id="recordingIdDisplay"'));
  assert.ok(!pageHtml.includes('앨범 가수 ID :'));
  assert.match(pageHtml, /id="albumArtistIdInput" type="hidden"/);
  assert.match(pageHtml, /id="cur_album_artist_id" hidden/);
  assert.ok(pageHtml.includes('id="albumArtistIdSearch" type="button" hidden'));
  assert.ok(!pageHtml.includes('MusicBrainz Album Artist ID'));
  assert.ok(pageHtml.includes('id="artistIdInput"'));
  assert.ok(!pageHtml.includes('id="itunesArtistIdDisplay"'));
  assert.ok(!pageHtml.includes('id="identifierEditor"'));
  assert.ok(!pageHtml.includes('기타 식별자'));
  assert.ok(pageHtml.includes('id="artistIdInput"'));
  assert.ok(!html.includes('id="itunesArtistIdDisplay"'));
  assert.ok(html.includes('현재 버전'));
  assert.ok(html.includes('id="updateClose"'));
  const updaterUI=harness();
  const panel=updaterUI.$('updaterPanel');
  panel.open=true;
  updaterUI.documentEvents.pointerdown({target:panel});
  assert.equal(panel.open,true); // Clicking within panel does not close it.
  updaterUI.$('updateClose').listeners.click();
  assert.equal(panel.open,false);
  panel.open=true;
  updaterUI.documentEvents.pointerdown({target:updaterUI.$('scanControls')});
  assert.equal(panel.open,false); // Outside pointer closes the panel.
  assert.equal(playback.$('headerAudio').textContent,'▶');

  const emptyCover=harness();
  emptyCover.context.coverJob={id:'cover-empty',results:[{path:'cover.mp3',file_state:'auto',original:{has_cover:true,revision:'a'.repeat(64)},candidates:[{id:'no-image',title:'Song'}],selected_id:'no-image'}]};
  emptyCover.run('adoptJob(coverJob)');
  emptyCover.run("editingResult._candidateId='no-image';editingResult._selection='manual'");
  assert.equal(emptyCover.run('saveItem(editingResult).include_cover'),false);
  emptyCover.run("editingResult.candidates[0].album='Album'");
  assert.equal(emptyCover.run('saveItem(editingResult).include_cover'),true);
  emptyCover.run("candidateCoverCache.set(candidateCoverUrl(editingResult.candidates[0],editingResult),{status:'failed'})");
  assert.equal(emptyCover.run('saveItem(editingResult).include_cover'),false);
  assert.equal(emptyCover.run('plannedChanges(editingResult).cover'),false);
  emptyCover.run("editingResult._coverId='valid-upload'");
  assert.equal(emptyCover.run('saveItem(editingResult).include_cover'),true);
  emptyCover.$('saveCover').checked=false;
  assert.equal(emptyCover.run('saveItem(editingResult).include_cover'),false);
  assert.equal(emptyCover.run('saveItem(editingResult).cover_id'),null);

  const list=harness();
  assert.equal(list.$('fileBody').children.length,13);
  assert.ok(list.$('fileBody').children.every(row=>row.className==='file-empty'&&!row.innerHTML.includes('input')));
  list.context.listJob={id:'media-list',results:Array.from({length:6},(_,i)=>({path:'file'+i+'.mp3',file_state:'auto',original:{revision:'a'.repeat(64),has_cover:i%2===0,has_lyrics:i%3===0},lyrics:'Online result must not set stored flag'}))};
  list.run('adoptJob(listJob)');
  assert.equal(list.$('fileBody').children.length,13);
  assert.equal(list.$('fileBody').children.filter(row=>row.className==='file-empty').length,7);
  const retainedRow=list.$('fileBody').children[0];const retainedMarkup=retainedRow.innerHTML;
  list.run('renderFileList()');assert.equal(list.$('fileBody').children[0],retainedRow);assert.equal(retainedRow.innerHTML,retainedMarkup);
  assert.ok(retainedMarkup.includes('data-file-thumbnail'));assert.ok(retainedMarkup.includes('file-lyrics has-lyrics'));
  const noMedia=list.$('fileBody').children[1].innerHTML;assert.ok(!noMedia.includes('data-file-thumbnail'));assert.ok(!noMedia.includes('file-lyrics has-lyrics'));
  assert.ok(retainedMarkup.indexOf('audio-preview-button')<retainedMarkup.indexOf('file-cover'));
  assert.ok(retainedMarkup.indexOf('file-cover')<retainedMarkup.indexOf('file-lyrics'));
  assert.ok(retainedMarkup.indexOf('file-lyrics')<retainedMarkup.indexOf('file-name-text'));
  list.run("currentResults[0].file_state='saved';renderFileList()");assert.equal(list.$('fileBody').children[0],retainedRow);
  list.context.longJob={id:'long-list',results:Array.from({length:20},(_,i)=>({path:i+'.mp3',original:{revision:'a'.repeat(64)}}))};
  list.run('adoptJob(longJob)');assert.equal(list.$('fileBody').children.length,20);
  assert.ok(!list.$('fileBody').children.some(row=>row.className==='file-empty'));
  assert.ok(html.includes("root:$('fileListScroller'),rootMargin:'0px'"));
  list.run("editingResult._selection='edit';editingResult._draft.title='Known';editingResult._draft.artist='Singer';editingResult.original.has_lyrics=true");
  list.$('fillLyrics').checked=true;
  assert.equal(list.run('!!plannedChanges(editingResult).lyrics'),false);
  list.run('editingResult.original.has_lyrics=false');assert.equal(list.run('!!plannedChanges(editingResult).lyrics'),false);
  list.run('editingResult.original.has_lyrics=true;editingResult.original.lyrics_marker=true');assert.equal(list.run('!!plannedChanges(editingResult).lyrics'),false);


  const lyricUI=harness();lyricUI.context.storedLyricText='Stored line one\nStored line two';
  lyricUI.context.lyricJob={id:'lyrics-ui',results:[{path:'with.mp3',original:{title:'Song one',artist:'Singer',has_lyrics:true,revision:'a'.repeat(64)},candidates:[]},{path:'without.mp3',original:{title:'Song two',artist:'Singer',has_lyrics:false,revision:'b'.repeat(64)},candidates:[]}]};
  lyricUI.run('adoptJob(lyricJob)');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(lyricUI.$('currentLyrics').textContent,'Stored line one\nStored line two');assert.equal(lyricUI.$('changeLyrics').value,'');
  lyricUI.$('fillLyrics').checked=true;lyricUI.run('updateSavePreview()');assert.equal(lyricUI.$('changeLyrics').value,'');
  assert.equal(lyricUI.calls.filter(c=>c.url.endsWith('/lyrics-search')).length,0);
  const lyricFetch=lyricUI.context.fetch;let finishLyric,lyricRequests=0;
  lyricUI.context.fetch=(url,options)=>{if(url.endsWith('/lyrics-search')){lyricRequests++;return new Promise(resolve=>finishLyric=resolve);}return lyricFetch(url,options);};
  const pendingLyric=lyricUI.run('searchLyricsForCurrent()');await lyricUI.run('searchLyricsForCurrent()');
  assert.equal(lyricRequests,1);assert.equal(lyricUI.$('changeLyrics').placeholder,'검색 중...');
  lyricUI.run('selectFile(1)');assert.equal(lyricUI.$('currentLyrics').textContent,'가사 없음');assert.equal(lyricUI.$('changeLyrics').value,'');
  lyricUI.run("adoptJob({id:'lyrics-ui',results:currentResults.map(r=>({...r,original:{...r.original}}))})");
  finishLyric({ok:true,text:async()=>JSON.stringify({status:'found',searched:true,lyrics:'Found line one\nFound line two',lyrics_id:'verified-id'})});await pendingLyric;
  assert.equal(lyricUI.$('changeLyrics').value,'');
  lyricUI.run('selectFile(0)');assert.notEqual(lyricUI.$('changeLyrics').value,'Found line one\nFound line two');
  lyricUI.context.fetch=lyricFetch;lyricUI.context.lyricResponse={status:'found',searched:true,lyrics:'Found line one\nFound line two',lyrics_id:'verified-id'};
  await lyricUI.run('searchLyricsForCurrent()');assert.equal(lyricUI.$('changeLyrics').value,'Found line one\nFound line two');
  assert.equal(lyricUI.run('saveItem(editingResult).lyrics_id'),'verified-id');
  lyricUI.$('onlyEmpty').checked=true;assert.equal(lyricUI.run('!!plannedChanges(editingResult).lyrics'),false);
  lyricUI.$('onlyEmpty').checked=false;assert.equal(lyricUI.run('!!plannedChanges(editingResult).lyrics'),true);
  const beforeLyricCheck=lyricUI.run('draftSignature(editingResult)');lyricUI.$('saveLyrics').checked=false;lyricUI.$('saveLyrics').listeners.change();
  assert.equal(lyricUI.run('draftSignature(editingResult)'),beforeLyricCheck);assert.equal(lyricUI.run('saveItem(editingResult).lyrics_id'),null);assert.equal(lyricUI.run('!!plannedChanges(editingResult).lyrics'),false);
  lyricUI.run('selectFile(1);selectFile(0)');assert.equal(lyricUI.$('saveLyrics').checked,false);
  lyricUI.$('saveLyrics').checked=true;lyricUI.run('toggleTagPreview()');assert.equal(lyricUI.$('currentLyrics').textContent,'Found line one\nFound line two');assert.ok(lyricUI.$('currentLyrics').className.includes('lyrics-preview'));
  lyricUI.run('toggleTagPreview()');assert.equal(lyricUI.$('currentLyrics').textContent,'Stored line one\nStored line two');
  assert.equal(lyricUI.calls.filter(c=>c.url.startsWith('/api/lyrics/')).length,1);
  lyricUI.context.fetch=lyricFetch;lyricUI.context.lyricResponse={status:'not_found',searched:true,lyrics:'',lyrics_id:'none-id'};
  await lyricUI.run('searchLyricsForCurrent()');assert.equal(lyricUI.$('changeLyrics').value,'Found line one\nFound line two');assert.equal(lyricUI.run('!!plannedChanges(editingResult).lyrics'),true);
  lyricUI.context.fetch=async()=>{throw new Error('offline');};await lyricUI.run('searchLyricsForCurrent()');assert.equal(lyricUI.$('changeLyrics').value,'Found line one\nFound line two');assert.notEqual(lyricUI.$('changeLyrics').placeholder,'검색 결과 없음');
  assert.ok(html.includes('.file-lyrics+.file-name-text{margin-left:6px}'));assert.ok(html.includes('height:210px'));assert.ok(!html.includes('<textarea id="currentLyrics"'));

  const manualUI=harness();
  manualUI.context.manualJob={id:'manual-current',results:[{path:'generated.mp3',original:{title:'',artist:'',revision:'a'.repeat(64)},candidates:[]}]};
  manualUI.run('adoptJob(manualJob)');
  for(const onlyEmpty of [false,true])for(const checked of [false,true]){
    manualUI.$('onlyEmpty').checked=onlyEmpty;
    manualUI.run(`commonTagFields=${checked?"['title','artist']":"[]"};updateSavePreview()`);
    manualUI.$('chg_title').value='너 때문에';manualUI.$('chg_title').listeners.input();
    manualUI.$('chg_artist').value='After School';manualUI.$('chg_artist').listeners.input();
    manualUI.context.lyricResponse={status:'found',lyrics:'Fixture candidate one lyric text',lyrics_id:'manual-one',query_title:'너 때문에',query_artist:'After School',choices:[
      {status:'found',lyrics:'Fixture candidate one lyric text',lyrics_id:'manual-one',title:'너 때문에',artist:'After School',album:'One',record_id:1},
      {status:'found',lyrics:'Fixture candidate two lyric text',lyrics_id:'manual-two',title:'너 때문에',artist:'After School',album:'Two',record_id:2}]};
    await manualUI.run('searchLyricsForCurrent()');
    const body=manualUI.calls.filter(c=>c.url.endsWith('/lyrics-search')).at(-1).body;
    assert.equal(body.title,'너 때문에');assert.equal(body.artist,'After School');assert.equal(body.force,true);
    assert.equal(manualUI.$('changeLyrics').value,'Fixture candidate one lyric text');assert.equal(manualUI.$('manualLyricsChoices').hidden,false);
    manualUI.run('selectManualLyrics(1)');assert.equal(manualUI.$('changeLyrics').value,'Fixture candidate two lyric text');
    assert.equal(manualUI.run('lyricChoice(editingResult,true)?.lyrics_id||null'),'manual-two');
  }
  assert.equal(manualUI.calls.filter(c=>c.url.endsWith('/save')).length,0);
  manualUI.context.lyricResponse={status:'not_found',message:''};await manualUI.run('searchLyricsForCurrent()');
  assert.equal(manualUI.$('manualLyricsStatus').textContent,'검색 결과 없음');
  manualUI.context.lyricResponse={status:'error',message:'LRCLIB API 오류 (HTTP 502)'};await manualUI.run('searchLyricsForCurrent()');
  assert.equal(manualUI.$('manualLyricsStatus').textContent,'LRCLIB API 오류 (HTTP 502)');
  manualUI.$('chg_title').value='New unsaved title';manualUI.$('chg_title').listeners.input();
  manualUI.run('selectManualLyrics(0)');assert.equal(manualUI.$('changeLyrics').value,'Fixture candidate two lyric text');
  manualUI.run("applyPathChange({seq:1,old_path:'generated.mp3',new_path:'renamed.mp3',revision:'a'.repeat(64),lyrics_tokens:[{old_id:'manual-one',new_id:'renamed-one'},{old_id:'manual-two',new_id:'renamed-two'}]})");
  assert.equal(manualUI.run('editingResult._lyricsSearch.choices[1].lyrics_id'),'renamed-two');
  const media=harness(),requests=[],pending=[];
  media.context.URL={createObjectURL:()=> 'blob:test-'+requests.length,revokeObjectURL(){}};
  media.context.fetch=(url,options={})=>{requests.push({url,options});return new Promise(resolve=>pending.push(resolve));};
  media.context.mediaRow={path:'fake.mp3',original:{revision:'a'.repeat(64)},candidates:Array.from({length:12},(_,i)=>({id:'c'+i,album:'Album '+i,title:'Title '+i,artist:'Singer'}))};
  media.$('candidateScroller').getBoundingClientRect=()=>({top:0,bottom:100});
  const createMedia=media.context.document.createElement;let rowIndex=0;
  media.context.document.createElement=tag=>{const node=createMedia(tag);if(tag==='tr'){const i=rowIndex++;node.getBoundingClientRect=()=>({top:i*30,bottom:i*30+30});}return node;};
  media.run("currentJobId='media';mediaJobStatus='done';renderCandidates(mediaRow)");
  assert.equal(requests.length,2); // completed jobs prefetch visible candidate media
  media.$('candidateScroller').onmouseenter();
  assert.equal(media.run('candidateCoverRunning+candidateLyricsRunning'),2);
  assert.equal(media.run('candidateCoverCache.size'),4);assert.equal(media.run('candidateLyricsCache.size'),4);
  assert.equal(media.run('requestCandidateCover(mediaRow.candidates[0],mediaRow)===requestCandidateCover(mediaRow.candidates[0],mediaRow)'),true);
  const coverResponses=pending.slice(0,3);
  for(const resolve of coverResponses)resolve({ok:true,blob:async()=>({type:'image/jpeg'})});
  for(let i=0;i<10;i++)await Promise.resolve();
  assert.ok(media.run('candidateCoverRunning')<=3);
  assert.equal(media.$('candidateThumb1-0').dataset.state,'ready');
  const cacheBefore=media.run('candidateCoverCache.size');
  media.$('candidateScroller').onscroll();assert.equal(media.run('candidateCoverCache.size'),cacheBefore);
  // Stale hover completions never repaint the newer hovered candidate.
  media.run('showHoverCover(mediaRow.candidates[0],mediaRow);hideHoverCover()');
  await Promise.resolve();assert.equal(media.$('hoverPrev').style.display,'none');
  assert.ok(html.includes('thumb.ondblclick='));assert.ok(html.includes('event.stopPropagation();clearTimeout(clickTimer)'));
  assert.ok(!html.includes('onclick="applyCoverToAll()"'));
  assert.ok(html.includes('width:24px;height:24px;object-fit:cover'));
  assert.ok(!html.includes('id="checkAllChange"'));
  assert.ok(html.includes('id="saveCover" checked aria-label="커버 이미지 저장"'));
  assert.ok(html.includes('#saveCover{position:absolute;top:4px;left:4px;width:14px;height:14px;'));
  const hoverOnly=harness();
  hoverOnly.context.row={path:'test.mp3',candidates:[{id:'one',album:'Album'}]};
  hoverOnly.run("currentJobId='thumb-only';renderCandidates(row)");
  const candidateRow=hoverOnly.$('candBody').children.at(-1),thumbnail=hoverOnly.$('candidateThumb1-0');
  assert.equal(candidateRow.onmouseenter,undefined);assert.equal(candidateRow.onmousemove,undefined);assert.equal(typeof candidateRow.onclick,'function');
  thumbnail.onmouseenter();assert.equal(hoverOnly.$('hoverPrev').style.display,'block');
  thumbnail.onmouseleave();assert.equal(hoverOnly.$('hoverPrev').style.display,'none');
  assert.ok(html.includes('#fileListScroller{height:517px;min-height:517px;max-height:517px;overflow-y:auto}'));
  assert.ok(html.includes('#fileColumn thead tr{height:37px}#fileBody tr{height:calc(480px / 13)}'));
  assert.match(html,/<label><input type="checkbox" class="chg-check" data-field="album" checked><\/label><div>앨범 :<\/div><input id="chg_album"/);
  const renamed=harness();
  renamed.run("currentJobId='rename';adoptJob({id:'rename',results:[{path:'before.mp3',file_state:'auto',scan_auto_selected:true,original:{revision:'a'.repeat(64),title:'Original'},candidates:[]}]});currentResults[0]._checked=true;currentResults[0]._displayOrder=7;$('chg_title').value='Unsaved draft';captureCurrent();currentResults[0]._dirty=true;playingPath='before.mp3';audioPlaying=true");
  renamed.$('previewAudio').src='/api/audio/before.mp3';renamed.$('fileListScroller').scrollTop=123;
  renamed.run("applyPathChange({seq:1,old_path:'before.mp3',new_path:'after.mp3',revision:'a'.repeat(64),lyrics_tokens:[]})");
  assert.equal(renamed.run('playingPath'),null);assert.equal(renamed.$('previewAudio').src,'');
  assert.equal(renamed.run('editingResult.path'),'after.mp3');assert.equal(renamed.run('editingResult._draft.title'),'Unsaved draft');
  assert.equal(renamed.run('editingResult._checked'),true);assert.equal(renamed.run('editingResult._displayOrder'),7);assert.equal(renamed.run('editingResult.file_state'),'auto');
  assert.equal(renamed.$('fileListScroller').scrollTop,123);
  renamed.run("playingPath='other.mp3';audioPlaying=true;stopRenamedAudio('after.mp3')");assert.equal(renamed.run('playingPath'),'other.mp3');
  const callsBefore=renamed.calls.length;
  renamed.run("renameEditor={stem:'same',input:{value:'same'}}");await renamed.run('submitFilenameEdit()');assert.equal(renamed.calls.length,callsBefore);assert.equal(renamed.run('renameEditor'),null);
  const ops=harness();
  ops.run('renderOperationStatus([])');assert.equal(ops.$('operationStatus').hidden,true);
  ops.run("renderOperationStatus([{message:'가사 검색 중...',path:'Folder/a.mp3',file:'a.mp3'}])");
  assert.equal(ops.$('operationStatus').hidden,false);assert.equal(ops.$('operationSummary').textContent,'가사 검색 중...');assert.equal(ops.$('operationArrow').hidden,true);
  ops.run("renderOperationStatus([{message:'가사 검색 중...',path:'Folder/a.mp3',file:'a.mp3'},{message:'앨범 이미지 검색 중...',path:'Folder/b.mp3',file:'b.mp3'}]);toggleOperationDetails()");
  assert.equal(ops.$('operationSummary').textContent,'백그라운드 작업 2건 진행 중');assert.equal(ops.$('operationDetails').hidden,false);assert.ok(ops.$('operationDetails').innerHTML.includes('b.mp3'));
  ops.run('toggleOperationDetails()');assert.equal(ops.$('operationDetails').hidden,true);
  ops.run('renderOperationStatus([])');assert.equal(ops.$('operationStatus').hidden,true);assert.equal(ops.run('operationExpanded'),false);
  const coverOnly=harness();coverOnly.$('onlyEmpty').checked=false;
  coverOnly.run("requestCandidateCover=()=>Promise.resolve(null);adoptJob({id:'cover-only',results:[{path:'cover.mp3',original:{revision:'a'.repeat(64),title:'Original',has_cover:true},candidates:[{id:'blue',title:'Changed title',album:'Changed album',cover_url:'https://example.invalid/blue.jpg'}]}]});applyCandidate(editingResult,editingResult.candidates[0]);toggleAllChange(false);captureCurrent()");
  assert.equal(coverOnly.run('saveItem(editingResult).include_cover'),true,'candidate cover must not depend on text checkboxes');
  assert.equal(coverOnly.run('plannedChanges(editingResult).cover'),true);
  assert.equal(coverOnly.run('saveItem(editingResult).fields.length'),0);
  coverOnly.$('saveCover').checked=false;assert.equal(coverOnly.run('saveItem(editingResult).include_cover'),false);
  coverOnly.$('saveCover').checked=true;coverOnly.$('onlyEmpty').checked=true;assert.equal(coverOnly.run('plannedChanges(editingResult).cover'),false);
  const pathTip=harness();pathTip.context.window={innerWidth:1000,innerHeight:800};
  pathTip.$('folderToggle').getBoundingClientRect=()=>({left:20,top:40,bottom:60});pathTip.$('buttonTooltip').getBoundingClientRect=()=>({width:320,height:60});
  pathTip.run("pendingFolder='DANCE/Fitness Latino Path Full';folderLabel()");pathTip.$('folderToggle').listeners.mouseenter();
  assert.equal(pathTip.$('buttonTooltip').textContent,'DANCE/Fitness Latino Path Full');assert.equal(pathTip.$('buttonTooltip').hidden,false);
  pathTip.$('folderToggle').listeners.mouseleave();assert.equal(pathTip.$('buttonTooltip').hidden,true);
  const jobView=harness();jobView.context.jobsResponse=[{id:'internal-id',status:'scanning',sub_path:'DANCE/Dance',scanned:1,total:30,current_file:'DANCE/An extremely long music filename.mp3',results:[]}];
  await jobView.run('pollJobs()');const jobMarkup=jobView.$('jobs').children[0].innerHTML;
  assert.ok(jobMarkup.includes('[1/30] DANCE/Dance'));assert.ok(!jobMarkup.includes('internal-id —'));
  assert.ok(jobMarkup.includes('class="job-current-file"'));assert.ok(jobMarkup.includes('An extremely long music filename.mp3'));memory.clear();
  const common=harness();
  common.context.commonJob={id:'common-fields',results:[{path:'one.mp3',file_state:'auto',original:{title:'One',album:'Dance CD1',revision:'a'.repeat(64)}},{path:'two.mp3',file_state:'auto',original:{title:'Two',album:'Dance CD2',revision:'a'.repeat(64)}}]};
  common.run('adoptJob(commonJob)');
  common.context.document.querySelectorAll('.chg-check').find(c=>c.dataset.field==='album').checked=false;common.context.document.querySelectorAll('.chg-check').find(c=>c.dataset.field==='album').listeners.change();
  common.run('captureCurrent()');
  await common.run('requestSelectFile(1)');
  assert.equal(common.$('actionDialog').open,undefined);
  assert.equal(common.run('editingResult.path'),'two.mp3');
  assert.equal(common.context.document.querySelectorAll('.chg-check').find(c=>c.dataset.field==='album').checked,false);
  assert.equal(common.run("currentResults.every(r=>!saveItem(r).fields.includes('album'))"),true);
  common.run("editingResult.original.has_cover=true;editingResult._coverId='uploaded-token'");common.$('saveCover').checked=false;common.$('saveCover').listeners.change();
  assert.ok(common.$('changeCover').innerHTML.includes('/api/cover/'));assert.ok(!common.$('changeCover').innerHTML.includes('uploaded-cover'));
  assert.equal(common.run('saveItem(editingResult).include_cover'),false);assert.equal(common.run('saveItem(editingResult).cover_id'),null);assert.equal(common.run('plannedChanges(editingResult).cover'),false);
  common.run('editingResult._coverId=null');await common.run('requestSelectFile(0)');assert.equal(common.$('actionDialog').open,undefined);
  assert.equal(common.$('saveCover').checked,false);await common.run('requestSelectFile(1)');
  common.run('currentResults.forEach(r=>r._checked=true)');
  const withoutCovers=common.run('saveSelected()');common.run('resolveAction(true)');await withoutCovers;
  const coverRequest=common.calls.filter(c=>c.url.endsWith('/save')).at(-1).body;
  assert.equal(coverRequest.save_cover,false);assert.ok(coverRequest.items.every(i=>!i.include_cover&&i.cover_id===null));
  common.$('chg_title').value='Unsaved edit';common.$('chg_title').listeners.input();
  const stay=common.run('requestSelectFile(0)');assert.equal(common.$('actionTitle').textContent,'미저장 변경사항');
  assert.equal(common.$('actionAccept').textContent,'버리고 이동');assert.equal(common.$('actionCancel').textContent,'계속 편집');
  common.run('resolveAction(false)');await stay;assert.equal(common.run('editingResult.path'),'two.mp3');assert.equal(common.$('chg_title').value,'Unsaved edit');
  const leave=common.run('requestSelectFile(0)');common.run('resolveAction(true)');await leave;
  await common.run('requestSelectFile(1)');assert.equal(common.$('chg_title').value,'Two');
  common.run('adoptJob(commonJob)');common.run('selectFile(1)');assert.equal(common.$('chg_title').value,'Two');
  assert.equal(common.context.document.querySelectorAll('.chg-check').find(c=>c.dataset.field==='album').checked,false);

  const progress=harness();
  progress.context.tasks=[{id:'first',job_id:'one',status:'saving',saved:23,total:49,processed:25,failed:1,skipped:1,partial:0,current_file:'<long>.mp3',current_path:'/music/folder/<long>.mp3'},{id:'second',job_id:'two',status:'done',saved:2,total:2,processed:2,failed:0,skipped:0,partial:0}];
  progress.run('renderSaveTasks(tasks)');
  assert.ok(progress.$('jobs').children[0].innerHTML.includes('[23/49]'));
  assert.ok(progress.$('jobs').children[0].innerHTML.includes('실패 1개'));
  assert.ok(progress.$('jobs').children[0].innerHTML.includes('title="/music/folder/&lt;long&gt;.mp3"'));
  assert.ok(progress.$('jobs').children[0].innerHTML.indexOf('class="progress"')>progress.$('jobs').children[0].innerHTML.indexOf('class="save-current-file"'));
  assert.ok(progress.$('jobs').children[1].innerHTML.includes('[2/2]'));
  assert.ok(progress.$('jobs').children[1].innerHTML.includes('badge-ok'));

  for(const [state,bg,fg] of [['auto','#E6F1FF','#175CD3'],['review','#FFF0D6','#A65B00'],['saved','#E4F5E9','#207245']]){
    assert.ok(html.includes('.file-state-'+state+'{background:'+bg+';color:'+fg+'}'));
  }
  assert.ok(html.includes('font-size:11px;line-height:1.5;white-space:nowrap;color-scheme:light'));
  const sorting=harness();
  sorting.run("currentResults=[{path:'z.mp3',file_state:'review'},{path:'b.mp3',file_state:'auto',_checked:true},{path:'a.mp3',file_state:'saved'},{path:'c.mp3',file_state:'auto',_checked:false}];currentResults.forEach(r=>r.original={revision:'a'.repeat(64)});filteredResults=currentResults.slice();selectFile(1)");
  sorting.$('chg_title').value='Unsaved title';
  sorting.run("captureCurrent();editingResult._dirty=true");
  const invariant=()=>sorting.run("JSON.stringify({paths:currentResults.map(r=>r.path),checks:currentResults.map(r=>r._checked),selected:editingResult.path,draft:editingResult._draft,fields:editingResult._fields,dirty:editingResult._dirty,targets:saveTarget().rows.map(r=>r.path)})");
  const beforeSort=invariant();
  const sortedPaths=()=>sorting.run("filteredResults.map(r=>r.path).join(',')");
  sorting.run("sortFiles('state')");assert.equal(sortedPaths(),'b.mp3,c.mp3,z.mp3,a.mp3');assert.equal(invariant(),beforeSort);
  assert.equal(sorting.$('fileStateHeader').attributes['aria-sort'],'ascending');
  sorting.run("sortFiles('state')");assert.equal(sortedPaths(),'a.mp3,z.mp3,b.mp3,c.mp3');assert.equal(invariant(),beforeSort);
  sorting.run("sortFiles('name')");assert.equal(sortedPaths(),'a.mp3,b.mp3,c.mp3,z.mp3');assert.equal(invariant(),beforeSort);
  sorting.run("sortFiles('name')");assert.equal(sortedPaths(),'z.mp3,c.mp3,b.mp3,a.mp3');assert.equal(invariant(),beforeSort);
  sorting.$('fileFilter').value='b.mp3';sorting.run('applyFilter()');assert.equal(sortedPaths(),'b.mp3');assert.equal(invariant(),beforeSort);
  sorting.$('fileFilter').value='';sorting.run('applyFilter()');assert.equal(sortedPaths(),'z.mp3,c.mp3,b.mp3,a.mp3');assert.equal(invariant(),beforeSort);
  sorting.run('toggleSelectAll(true)');assert.equal(sorting.run('saveTarget().rows.length'),2);
  for(const [state,label] of [['auto','자동선택'],['review','확인필요'],['saved','저장완료']]){
    const row=sorting.$('fileBody').children.filter(r=>r.innerHTML.includes('file-state-'+state)).at(-1);
    assert.ok(row&&row.innerHTML.includes(label));
    assert.equal(row.innerHTML.includes('disabled'),state!=='auto');
  }
  const fixedOrder=sortedPaths();
  sorting.run("currentResults.find(r=>r.path==='b.mp3').file_state='saved';currentResults.find(r=>r.path==='z.mp3').file_state='auto';renderFileList()");
  assert.equal(sortedPaths(),fixedOrder);assert.equal(sorting.run("filteredResults.find(r=>r.path==='b.mp3')._checked"),false);
  assert.ok(sorting.$('fileBody').children.filter(r=>r.innerHTML.includes('b.mp3')).at(-1).innerHTML.includes('disabled'));
  sorting.run('applyFilter()');assert.equal(sortedPaths(),fixedOrder);
  sorting.run("sortFiles('state')");assert.equal(sortedPaths(),'c.mp3,z.mp3,a.mp3,b.mp3');
  assert.equal(sorting.run('editingResult.path'),'b.mp3');assert.equal(sorting.$('chg_title').value,'Unsaved title');
  sorting.run("displayedJobId='sort-job';adoptJob({id:'sort-job',results:currentResults.map(r=>({...r,original:{...r.original,revision:'updated'}}))})");
  assert.equal(sortedPaths(),'c.mp3,z.mp3,a.mp3,b.mp3');

  const savedOrder=harness();
  savedOrder.context.fixture={id:'saved-order',results:[{path:'b.mp3',file_state:'auto',_checked:true,original:{revision:'a'.repeat(64)}},{path:'a.mp3',file_state:'review',original:{revision:'a'.repeat(64)}}]};
  savedOrder.run("adoptJob(fixture);sortFiles('state')");
  const beforeSave=savedOrder.run("filteredResults.map(r=>r.path).join(',')");
  savedOrder.context.saveResponse={saved:1,failed:0,skipped:0,partial:0,results:[{request_path:'b.mp3',path:'renamed.mp3',changed:true,file_state:'saved',status:'saved',original:{title:'Saved',revision:'b'.repeat(64)}}]};
  const bodyModel=savedOrder.$('fileBody');let bodyMarkup=bodyModel.innerHTML;
  Object.defineProperty(bodyModel,'innerHTML',{get(){return bodyMarkup;},set(value){bodyMarkup=value;savedOrder.$('fileListScroller').scrollTop=0;}});
  savedOrder.$('fileListScroller').scrollTop=200;
  const savingOrder=savedOrder.run('saveCurrent()');savedOrder.run('resolveAction(true)');await savingOrder;
  assert.equal(savedOrder.$('fileListScroller').scrollTop,200);
  assert.equal(beforeSave,'b.mp3,a.mp3');assert.equal(savedOrder.run("filteredResults.map(r=>r.path).join(',')"),'renamed.mp3,a.mp3');
  assert.equal(savedOrder.run('selectedFileIdx'),0);assert.equal(savedOrder.run('editingResult.file_state'),'saved');
  savedOrder.run("adoptJob({id:'saved-order',results:currentResults.map(r=>({...r}))})");
  assert.equal(savedOrder.run("filteredResults.map(r=>r.path).join(',')"),'renamed.mp3,a.mp3');assert.equal(savedOrder.$('fileListScroller').scrollTop,200);
  assert.match(html,/<h4>현재 태그 정보<\/h4>/);
  assert.match(html,/<div class="current-cover-column"><div class="cover" id="currentCover">[\s\S]*?<\/div><div id="tagPreviewLabel" hidden><span>변경태그<\/span><span>미리보기<\/span><\/div><\/div>/);
  assert.ok(html.includes('white-space:nowrap;word-break:keep-all;overflow-wrap:normal'));
  assert.match(html,/<div id="tagPreviewNote" hidden>빨간색 글씨는 저장 시 변경될 태그입니다\. 미리보기는 실제 파일을 변경하지 않습니다\.<br>커버 이미지 크기와 가사·파일명 등은 저장 시 최종 적용됩니다\.<\/div>/);
  assert.match(html,/#tagPreviewNote\{[^}]*border-top:1px solid var\(--line\);color:#78a5d2/);
  assert.ok(html.includes('id="changeSummary" hidden'));
  assert.ok(html.includes('id="saveScopeInfo" hidden'));

  assert.ok(!html.includes('id="btnStop"'));
  assert.ok(!script.includes('async function stopScan'));
  const scanUi=harness();
  const scanJob={id:'scan-stop',status:'scanning',sub_path:'',scanned:1,total:3,results:[],created_at:1};
  scanUi.context.jobsResponse=[scanJob];
  await scanUi.run('pollJobs()');
  assert.ok(scanUi.$('jobs').children[0].innerHTML.includes("cancelSpecific('scan-stop')"));
  const stopConfirmation=scanUi.run("cancelSpecific('scan-stop')");scanUi.run('resolveAction(true)');await stopConfirmation;
  assert.ok(scanUi.calls.some(c=>c.url==='/api/jobs/scan-stop/cancel'&&c.method==='POST'));
  scanJob.status='cancelling';await scanUi.run('pollJobs()');
  assert.match(scanUi.$('progressText').textContent,/전체 3곡.*검색 완료 1곡.*남은 2곡.*cancelling/);
  scanJob.status='cancelled';await scanUi.run('pollJobs()');
  assert.match(scanUi.$('progressText').textContent,/전체 3곡.*검색 완료 1곡.*남은 2곡.*cancelled/);
  assert.equal(scanUi.$('btnResume').style.display,'inline-block');
  const h=harness();
  h.run("musicFolders=['Album','Album/Disc1','Album/Disc1/Bonus','Album/Disc2','Other']; renderFolders()");
  h.$('folderToggle').onclick();assert.equal(h.$('folderMenu').hidden,false);
  assert(click(row(h,'Album').children[0],h));
  assert.equal(h.$('folderMenu').hidden,false);assert(row(h,'Album/Disc1'));
  click(row(h,'Album/Disc1').children[0],h);assert(row(h,'Album/Disc1/Bonus'));
  h.$('folderOptions').scrollTop=35;
  click(row(h,'Album').children[0],h);
  assert.equal(h.$('folderMenu').hidden,false);assert.equal(h.$('folderOptions').scrollTop,35);
  assert(!row(h,'Album/Disc1'));
  click(row(h,'Album').children[0],h);assert(row(h,'Album/Disc1/Bonus')); // descendant state survives ancestor collapse
  click(row(h,'Album/Disc2').children.at(-1),h);
  assert.equal(h.$('subPath').value,'');assert.equal(h.$('folderMenu').hidden,false);
  assert(h.$('folderToggle').textContent.includes('(임시)'));
  const rootScan=h.run('startScan()');assert.equal(h.calls.filter(c=>c.url==='/api/scan').length,0);h.run('resolveAction(true)');await rootScan;assert.equal(h.calls.find(c=>c.url==='/api/scan').body.sub_path,'');
  await h.run('confirmFolder()');assert.equal(h.$('subPath').value,'Album/Disc2');
  assert.equal(h.$('folderMenu').hidden,true);assert(!h.$('folderToggle').textContent.includes('(임시)'));
  h.documentEvents.click({target:{}});assert.equal(h.$('folderMenu').hidden,true);
  h.$('folderToggle').onclick();assert(row(h,'Album/Disc1/Bonus'));
  h.$('folderToggle').onclick();assert.equal(h.$('folderMenu').hidden,true);
  h.$('folderToggle').onclick();h.$('folderSearch').value='Bonus';h.run('renderFolders()');assert(row(h,'Album/Disc1/Bonus'));
  h.$('folderSearch').value='';h.run('renderFolders()');assert(row(h,'Album/Disc1/Bonus'));
  const reloaded=harness();reloaded.run("musicFolders=['Album','Album/Disc1','Album/Disc1/Bonus'];renderFolders()");
  assert(row(reloaded,'Album/Disc1/Bonus'));
  await h.run('loadPreferences()');assert.equal(h.$('recurse').checked,false);assert.equal(h.$('renameFiles').checked,false);
  assert.equal(h.$('artistPreference').value,'latin');
  const savedOptions=h.run('JSON.stringify(optionState())');const beforeModalCalls=h.calls.length;
  h.run('openSaveOptions()');assert.equal(h.$('saveOptionsDialog').open,true);
  h.$('renameFiles').checked=false;h.$('includeIds').checked=false;h.$('searchCountry').value='US';
  h.$('onlyEmpty').checked=false;h.$('fillLyrics').checked=false;
  h.$('artistPreference').value='original';h.$('coverMax').value=900;h.$('scanPaths').value='Unconfirmed';
  h.$('rememberOptions').checked=true;
  h.run('cancelSaveOptions()');assert.equal(h.$('saveOptionsDialog').open,false);
  assert.equal(h.run('JSON.stringify(optionState())'),savedOptions);assert.equal(h.calls.length,beforeModalCalls);
  h.run('openSaveOptions()');h.$('coverMax').value=600;h.$('onlyEmpty').checked=false;h.$('fillLyrics').checked=false;
  h.$('saveOptionsDialog').listeners.cancel({preventDefault(){}});
  assert.equal(h.run('JSON.stringify(optionState())'),savedOptions);
  assert.equal(h.$('onlyEmpty').checked,true);assert.equal(h.$('fillLyrics').checked,true);
  h.run('openSaveOptions()');h.$('coverMax').value=600;
  h.$('saveOptionsForm').valid=false;await h.run('applySaveOptions({preventDefault(){}})');assert.equal(h.$('saveOptionsDialog').open,true);
  h.$('saveOptionsForm').valid=true;await h.run('applySaveOptions({preventDefault(){}})');
  assert.equal(h.$('saveOptionsDialog').open,false);assert.equal(h.$('coverMax').value,600);assert.equal(h.calls.length,beforeModalCalls);
  h.run('openSaveOptions()');h.$('coverMax').value=500;h.$('rememberOptions').checked=true;
  await h.run('applySaveOptions({preventDefault(){}})');assert.equal(h.calls.at(-1).method,'PUT');
  await h.run('savePreferences()');assert.equal(h.calls.at(-1).body.cover_max_px,500);
  h.run('openSaveOptions()');h.$('onlyEmpty').checked=false;h.$('fillLyrics').checked=false;
  await h.run('applySaveOptions({preventDefault(){}})');
  assert.equal(h.$('onlyEmpty').checked,false);assert.equal(h.$('fillLyrics').checked,false);
  h.$('scanPaths').value='Album/one.mp3\nAlbum/Disc2\n';
  await h.run('startScan()');
  const scan=h.calls.filter(c=>c.url==='/api/scan').at(-1).body;
  assert.deepEqual(scan.paths,['Album/one.mp3','Album/Disc2']);assert.equal(scan.recurse,false);assert.equal(scan.country,'JP');
  assert.equal(scan.only_empty,false);assert.equal(scan.fill_lyrics,false);
  await h.run('pollJobs()');
  h.context.job={id:'work',results:[{path:'a.mp3',original:{title:'Old',artist:'Singer',revision:'a'.repeat(64)},candidates:[]},
    {path:'b.mp3',original:{title:'Other',revision:'b'.repeat(64)},candidates:[]}]};
  h.run('adoptJob(job)');await h.run('uploadCover({size:100,type:"image/png"})');
  assert.equal(h.run('editingResult._coverId'),'cover-token');assert.equal(h.run('editingResult._selection'),'edit');
  assert(!h.calls.some(c=>c.url.endsWith('/save')));
  const coverAllConfirmation=h.run('applyCoverToAll()');h.run('resolveAction(true)');await coverAllConfirmation;assert.equal(h.run('currentResults[1]._coverId'),'cover-token');
  const item=h.run('saveItem(currentResults[1])');assert.equal(item.cover_id,'cover-token');assert.equal(item.include_ids,true);
  h.$('onlyEmpty').checked=false;
  h.context.candidate={id:'latin',title:'Song',artist:'原文',artist_latin:'Latin',albumartist:'原文',album_artist_latin:'Latin'};
  h.run('applyCandidate(editingResult,candidate)');assert.equal(h.$('chg_artist').value,'Latin');assert.equal(h.$('chg_albumartist').value,'Latin');
  const confirmedSave=h.run('saveCurrent()');h.run('resolveSaveConfirm(true)');await confirmedSave;assert.equal(h.calls.filter(c=>c.url.endsWith('/save')).at(-1).body.rename,false);
  assert.equal(h.calls.filter(c=>c.url.endsWith('/save')).at(-1).body.only_empty,false);assert.equal(h.calls.filter(c=>c.url.endsWith('/save')).at(-1).body.fill_lyrics,false);assert.equal(h.calls.filter(c=>c.url.endsWith('/save')).at(-1).body.cover_max_px,500);
  const snapshot=h.run('jobSignature(job)');h.context.job.results[0].search_generation='new-generation';
  assert.notEqual(h.run('jobSignature(job)'),snapshot);
  h.run('selectFile(1)');h.$('chg_title').value='Draft';h.run('captureCurrent()');
  h.context.updated={id:'work',results:[{path:'a.mp3',original:{revision:'a'.repeat(64)},candidates:[]},
    {path:'b.mp3',original:{title:'External update',revision:'c'.repeat(64)},candidates:[]}]};
  h.run('adoptJob(updated)');assert.equal(h.run('editingResult.path'),'b.mp3');assert.equal(h.$('chg_title').value,'External update');
  // All requests below use the isolated fetch stub; no NAS scans or saves.
  memory.clear();const safety=harness();
  const cancelledRoot=safety.run('startScan()');
  assert.equal(safety.calls.length,0);assert.equal(safety.$('actionAccept').textContent,'전체 스캔 시작');
  assert.match(safety.$('actionMessage').textContent,/8만/);
  safety.run('resolveAction(false)');await cancelledRoot;assert.equal(safety.calls.length,0);
  const escapedRoot=safety.run('startScan()');safety.$('actionDialog').listeners.cancel({preventDefault(){}});
  await escapedRoot;assert.equal(safety.calls.length,0);
  await safety.run("pendingFolder='Album';confirmFolder()");
  await safety.run('startScan()');await safety.run('pollJobs()');
  assert.equal(safety.calls.filter(c=>c.url==='/api/scan').length,1);
  assert.equal(safety.$('actionDialog').open,false); // Individual folder has no warning.
  safety.context.job={id:'folder-job',sub_path:'Album',results:[{path:'Album/a.mp3',original:{title:'Original',revision:'a'.repeat(64)},candidates:[]}]};
  safety.run('adoptJob(job)');safety.$('chg_title').value='Unsaved';safety.$('chg_title').listeners.input();
  const continueEdit=safety.run('discardDraft()');assert.equal(safety.$('actionCancel').textContent,'계속 편집');
  assert.equal(safety.$('actionAccept').textContent,'편집 취소');
  safety.run('resolveAction(false)');await continueEdit;assert.equal(safety.$('chg_title').value,'Unsaved');
  const callsBeforeCancel=safety.calls.length,discard=safety.run('discardDraft()');safety.run('resolveAction(true)');await discard;
  assert.equal(safety.calls.length,callsBeforeCancel);assert.equal(safety.$('chg_title').value,'Original');
  safety.context.report={saved:2,skipped:3,failed:1,partial:1,state_error:'state error',results:[
    {path:'long/<script>.mp3',status:'failed',message:'bad <tag>',warning:'warning',rename_error:'rename error'},
    {path:'part.mp3',status:'partial',rename_error:'name conflict'},
    {path:'skip.mp3',status:'skipped',reason:'no_selection'}]};
  safety.run("reportSave(report,'selected',[],new Map())");assert.equal(safety.$('saveResultDialog').open,true);
  assert.match(safety.$('saveResultCounts').innerHTML,/저장 성공/);
  assert.match(safety.$('saveResultCounts').innerHTML,/일부 저장/);
  assert.match(safety.$('saveResultIssues').innerHTML,/&lt;script&gt;/);
  assert(!safety.$('saveResultIssues').innerHTML.includes('<script>'));
  assert.match(safety.$('saveResultIssues').innerHTML,/warning \/ rename error/);
  assert.equal(safety.$('saveResultState').textContent,'state error');
  assert(html.includes('overflow-wrap:anywhere'));assert(html.includes('max-height:280px;overflow-y:auto'));
  safety.$('fileFilter').value='a.mp3';safety.run('applyFilter();persistView()');
  const reload=harness();reload.context.jobsResponse=[{id:'other',sub_path:'Other',results:[]},safety.context.job];
  await reload.run('pollJobs()');assert.equal(reload.$('subPath').value,'Album');
  assert.equal(reload.$('folderToggle').textContent,'Album ▼');
  assert.equal(reload.run('displayedJobId'),'folder-job');assert.equal(reload.run('editingResult.path'),'Album/a.mp3');
  assert.equal(reload.$('fileFilter').value,'a.mp3');
  await reload.run("pendingFolder='Unscanned';confirmFolder()");assert.equal(reload.run('currentResults.length'),0);
  const emptyReload=harness();emptyReload.context.jobsResponse=reload.context.jobsResponse;
  await emptyReload.run('pollJobs()');assert.equal(emptyReload.$('subPath').value,'Unscanned');
  assert.equal(emptyReload.run('currentResults.length'),0);assert.equal(emptyReload.run('editingResult'),null);
  const optionHarness=harness();
  optionHarness.context.optionJob={id:'options',results:[{path:'one.mp3',original:{title:'Old',revision:'a'.repeat(64)},candidates:[{id:'option-candidate',album:'New Album'}]}]};
  optionHarness.$('fileFilter').value='';optionHarness.run('adoptJob(optionJob)');
  for(const enabled of [true,false]){
    for(const id of ['onlyEmpty','fillLyrics','renameFiles','includeIds'])optionHarness.$(id).checked=enabled;
    optionHarness.$('coverMax').value=enabled?100:1000;
    optionHarness.run('updateSavePreview();applyCandidate(editingResult,editingResult.candidates[0])');
    const pending=optionHarness.run('saveCurrent()');optionHarness.run('resolveAction(true)');await pending;
    const body=optionHarness.calls.filter(c=>c.url.endsWith('/save')).at(-1).body;
    assert.equal(body.only_empty,enabled);assert.equal(body.fill_lyrics,enabled);assert.equal(body.rename,false);
    assert.equal(body.items[0].include_ids,enabled);assert.equal(body.cover_max_px,enabled?100:1000);
  }
  const batch=harness();batch.context.jobsResponse=[{id:'done',status:'done',results:[]},{id:'stopped',status:'cancelled',results:[]},{id:'busy',status:'scanning',results:[]}];
  await batch.run('pollJobs()');batch.run('selectBackgroundJobs(true)');
  assert.equal(batch.run('selectedBackgroundJobs.size'),2);assert.equal(batch.$('deleteSelectedJobs').textContent,'선택 작업 삭제 (2건)');
  assert.ok(batch.$('jobs').children[0].innerHTML.includes("cancelSpecific('busy')"));
  const batchFetch=batch.context.fetch;
  batch.context.fetch=async(url,options={})=>{if(url==='/api/jobs/delete'){const ids=JSON.parse(options.body).ids;batch.context.jobsResponse=batch.context.jobsResponse.filter(j=>!ids.includes(j.id));}return batchFetch(url,options);};
  const beforeDelete=batch.calls.filter(c=>c.url==='/api/jobs/delete').length;
  const cancelBatch=batch.run('deleteSelectedBackgroundJobs()');batch.run('resolveAction(false)');await cancelBatch;
  assert.equal(batch.calls.filter(c=>c.url==='/api/jobs/delete').length,beforeDelete);
  const acceptBatch=batch.run('deleteSelectedBackgroundJobs()');batch.run('resolveAction(true)');await acceptBatch;
  const deleted=batch.calls.filter(c=>c.url==='/api/jobs/delete').at(-1);assert.deepEqual(deleted.body.ids,['done','stopped']);
  assert.equal(batch.run('allJobs.length'),1);assert.equal(batch.run('selectedBackgroundJobs.size'),0);
  const ordering=harness();ordering.context.jobsResponse=[
    {id:'done-scan',status:'done',created_at:9,record_version:9,results:[]},
    {id:'paused-scan',status:'interrupted',created_at:8,record_version:8,results:[]},
    {id:'queued-scan',status:'queued',created_at:1,record_version:1,results:[]},
    {id:'running-scan',status:'scanning',created_at:2,record_version:2,results:[]}
  ];
  ordering.run("renderSaveTasks([{id:'done-save',job_id:'done-scan',status:'done',created_at:10,finished_at:7,saved:1,total:1},{id:'running-save',job_id:'done-scan',status:'saving',created_at:3,saved:0,total:1},{id:'partial-save',job_id:'done-scan',status:'done',partial:1,created_at:4,saved:0,total:1}])");
  await ordering.run('pollJobs()');
  const orderedIds=ordering.$('jobs').children.map(row=>row.innerHTML.match(/data-job-select="([^"]+)/)?.[1]);
  assert.deepEqual(orderedIds,['save:running-save','scan:running-scan','scan:queued-scan','scan:paused-scan','save:partial-save','scan:done-scan','save:done-save']);
  ordering.run("toggleBackgroundJob('save:done-save',true)");
  ordering.run("renderSaveTasks(lastSaveTasks.map(task=>task.id==='done-save'?{...task,finished_at:12}:task))");
  assert.ok(ordering.$('jobs').children[5].innerHTML.includes('save:done-save'));
  assert.ok(ordering.$('jobs').children[5].innerHTML.includes('checked'));
  batch.run('currentResults=Array(10000);filteredResults=[];editingResult=null;renderFileList()');
  assert.equal(batch.$('fileColumn').style['--number-width'],'56px');
  assert.ok(html.includes('position:fixed;inset:0;margin:auto;box-sizing:border-box'));
  assert.ok(!/\bconfirm\(/.test(script));
  const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);assert.equal(ids.length,new Set(ids).size);
  assert(html.indexOf('id="scanControls"')<html.indexOf('id="fileColumn"'));
  assert(html.indexOf('id="scanControls"')<html.indexOf('파일 목록 <span'));
  assert(html.indexOf('id="scanControls"')>html.indexOf('<div class="main">'));
  const controlBlock=html.slice(html.indexOf('id="scanControls"'),html.indexOf('id="fileColumn"'));
  const order=['folderPicker','btnFolderConfirm','recurse','btnScan'].map(id=>controlBlock.indexOf('id="'+id+'"'));
  assert(order.every((index,i)=>index>=0&&(!i||index>order[i-1])));
  assert(!html.includes('<details'));assert(!html.includes('입력·저장 옵션'));
  assert(html.includes('#scanControls{grid-column:1/-1;justify-content:center;'));
  const stack=[],parents={};const voids=new Set(['area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr']);
  for(const token of html.split(/<script\b/)[0].matchAll(/<\/?([a-z][\w-]*)\b([^>]*)>/gi)){
    const name=token[1].toLowerCase();if(token[0].startsWith('</')){assert.equal(stack.pop()?.name,name);continue;}
    const id=token[2].match(/\bid="([^"]+)"/)?.[1];if(id)parents[id]=stack.at(-1);
    if(!voids.has(name))stack.push({name,id,attrs:token[2]});
  }
  assert.equal(parents.scanControls,parents.fileColumn);assert.equal(parents.fileColumn,parents.tagColumn);
  assert(parents.scanControls.attrs.includes('class="main"'));
  for(const id of ['onlyEmpty','fillLyrics','btnOptions'])assert(!controlBlock.includes('id="'+id+'"'));
  assert.equal(parents.onlyEmpty.name,'label');assert.equal(parents.fillLyrics.name,'label');
  const modal=html.slice(html.indexOf('<dialog'),html.indexOf('</dialog>'));
  assert(modal.includes('id="onlyEmpty" checked> 빈 태그만 채우기'));
  assert(modal.includes('id="fillLyrics"> 없는 가사 추가'));
  assert(modal.includes('title="기존 태그 값은 유지하고 비어 있는 항목만 채웁니다."'));
  assert(modal.includes('title="저장할 때 기존 가사가 없는 파일에 검증된 가사를 검색하여 추가합니다."'));
  const saveButtons=html.slice(html.indexOf('onclick="toggleTagPreview()"'),html.indexOf('id="lyricStatus"'));
  const buttonOrder=['toggleTagPreview()','saveCurrent()','saveAll()','resetChange()','openSaveOptions()'].map(fn=>saveButtons.indexOf(fn));
  assert(buttonOrder.every((index,i)=>index>=0&&(!i||index>buttonOrder[i-1])));
  const fingerprintPrefs=harness();
  fingerprintPrefs.context.preferencesResponse={country:'KR',recurse:true,only_empty:true,fill_lyrics:true,rename:false,include_ids:false,artist_name_preference:'original',cover_max_px:1000,use_fingerprint:true};
  await fingerprintPrefs.run('loadPreferences()');
  assert.equal(fingerprintPrefs.$('useFingerprint').checked,true);
  assert.equal(fingerprintPrefs.run('preferenceValues().use_fingerprint'),true);
  fingerprintPrefs.context.preferencesResponse.use_fingerprint=false;
  await fingerprintPrefs.run('loadPreferences()');
  assert.equal(fingerprintPrefs.$('useFingerprint').checked,false);
  assert.equal(fingerprintPrefs.$('fillLyrics').checked,true);
  assert(html.includes("use_fingerprint:mode==='sound'"));
  const timing=harness();
  timing.$('subPath').value='Album';timing.$('useFingerprint').checked=false;
  await timing.run('startScan()');
  assert.equal(timing.calls.find(c=>c.url==='/api/scan').body.use_fingerprint,false);
  timing.context.performance.now=()=>91250;
  timing.run("currentJobId='scan';observeScanCompletion({id:'scan',status:'done',scanned:20,scan_elapsed_seconds:90})");
  assert.equal(timing.$('progressText').textContent,'20곡 스캔 완료 · 1분 31.25초');
  assert.equal(timing.$('progressText').dataset.serverSeconds,'90');
  timing.context.performance.now=()=>999999;
  assert.equal(timing.run("scanCompletionText({id:'scan',scanned:20,scan_elapsed_seconds:90})"),'20곡 스캔 완료 · 1분 31.25초');
  // After reload, the persisted server duration is the fallback.
  assert.equal(harness().run("scanCompletionText({id:'persisted',scanned:20,scan_elapsed_seconds:91.25})"),'20곡 스캔 완료 · 1분 31.25초');
  assert.equal(timing.run('formatScanDuration(undefined)'),'0.00초');
  // Selected automatic cover is independent of candidate hover and list ordering.
  const flushCover=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
  function automaticCover(){
    const h=harness(),pending=[];
    h.context.URL={createObjectURL:()=> 'blob:auto-cover',revokeObjectURL(){}};
    h.context.fetch=url=>{if(url.endsWith('/candidate-lyrics'))return Promise.resolve({ok:true,text:async()=>JSON.stringify({status:'not_found',lyrics:''})});pending.push({url});return new Promise(resolve=>pending.at(-1).resolve=resolve);};
    h.context.autoJob={id:'auto-cover',results:[{path:'one.mp3',file_state:'auto',auto_apply:true,original:{revision:'r',title:'Original'},best:{id:'best',title:'Selected',album:'Best album'},candidates:[{id:'first',album:'Other album'},{id:'best',title:'Selected',album:'Best album'}]},{path:'two.mp3',original:{revision:'r2'}}]};
    h.run('adoptJob(autoJob)');return {h,pending};
  }
  const imageResponse={ok:true,blob:async()=>({type:'image/jpeg'})};
  const autoCover=automaticCover();
  assert.equal(autoCover.pending.length,1);assert.ok(autoCover.pending[0].url.includes('/cover/best?'));
  assert.ok(autoCover.h.$('changeCover').innerHTML.includes('이미지 조회 중'));
  const draftBefore=autoCover.h.run('draftSignature(editingResult)');
  autoCover.pending[0].resolve(imageResponse);await flushCover();
  assert.ok(autoCover.h.$('changeCover').innerHTML.includes('blob:auto-cover'));
  assert.equal(autoCover.h.run('draftSignature(editingResult)'),draftBefore);
  autoCover.h.run('selectFile(1);selectFile(0)');await flushCover();
  assert.equal(autoCover.pending.length,1);assert.ok(autoCover.h.$('changeCover').innerHTML.includes('blob:auto-cover'));
  const coverReloaded=automaticCover();assert.equal(coverReloaded.pending.length,1);
  coverReloaded.pending[0].resolve(imageResponse);await flushCover();assert.ok(coverReloaded.h.$('changeCover').innerHTML.includes('blob:auto-cover'));
  const staleCover=automaticCover();staleCover.h.run('selectFile(1)');staleCover.pending[0].resolve(imageResponse);await flushCover();
  assert.ok(!staleCover.h.$('changeCover').innerHTML.includes('blob:auto-cover'));
  const manualCover=automaticCover();manualCover.h.run("editingResult._coverId='manual';renderChangeCover(editingResult)");
  manualCover.pending[0].resolve(imageResponse);await flushCover();assert.ok(manualCover.h.$('changeCover').innerHTML.includes('/uploaded-cover/manual'));
  for(const state of ['none','error']){
    const empty=automaticCover();empty.pending[0].resolve({ok:false,status:state==='none'?404:503,json:async()=>({detail:{state,errors:state==='error'?['upstream']:[]}})});
    await flushCover();assert.ok(empty.h.$('changeCover').innerHTML.includes(state==='none'?'이미지 없음':'이미지 조회 오류'));
  }
  const protectedCover=harness();protectedCover.$('onlyEmpty').checked=true;
  protectedCover.context.autoJob=structuredClone(autoCover.h.context.autoJob);protectedCover.context.autoJob.results[0].original.has_cover=true;
  protectedCover.run('adoptJob(autoJob)');assert.equal(protectedCover.calls.filter(c=>c.url.includes('/cover/best?')).length,0);
  assert.ok(protectedCover.$('changeCover').innerHTML.includes('/api/cover/one.mp3'));
  manualCover.h.run("manualCoverDraft(editingResult,'remembered-manual')");
  const manualReload=automaticCover();assert.equal(manualReload.pending.length,0);
  assert.ok(manualReload.h.$('changeCover').innerHTML.includes('/uploaded-cover/remembered-manual'));
  assert.ok(manualReload.h.$('changeCover').innerHTML.includes('수동 선택 이미지 만료'));
  manualReload.h.run('resetDraft(editingResult);renderChangeCover(editingResult)');assert.equal(manualReload.pending.length,1);
  const afterDiscard=automaticCover();assert.equal(afterDiscard.pending.length,1);
  console.log('PASS: automatic selected cover, immediate repaint, cache/reload, stale/manual image protection, none/error and only-empty protection; existing P2 handlers preserved.');
})().catch(e=>{console.error(e);process.exitCode=1;});
