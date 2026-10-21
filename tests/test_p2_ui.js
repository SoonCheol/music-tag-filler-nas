// Actual page handlers in an isolated DOM model. No browser/NAS/music mutations.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('app/static/index.html', 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1]
  .replace(/^loadPreferences\(\);/m, '').replace(/^loadFolders\(\);/m, '').replace(/^pollJobs\(\);/m, '');
const memory = new Map();
function harness() {
  const elements = new Map(), checks = [], calls = [], documentEvents = {};
  function element() {return {value:'',checked:false,hidden:true,style:{},children:[],listeners:{},attributes:{},scrollTop:0,
    showModal(){this.open=true;},close(){this.open=false;},reportValidity(){return this.valid!==false;},
    innerHTML:'',textContent:'',classList:{add(){},remove(){}},setAttribute(k,v){this.attributes[k]=v;},focus(){},
    appendChild(child){child.parent=this;this.children.push(child);},replaceChildren(){this.children.forEach(c=>c.parent=null);this.children=[];},
    addEventListener(name,fn){this.listeners[name]=fn;},contains(target){return target===this||this.children.some(c=>c.contains(target));}};}
  function $(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}
  for(const field of ['title','artist','album','albumartist','track','year','genre']){const check=element();check.checked=true;check.dataset={field};checks.push(check);}
  const context=vm.createContext({console,Set,Map,Number,encodeURIComponent,localStorage:{getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v)},
    document:{getElementById:$,createElement:element,addEventListener:(k,f)=>documentEvents[k]=f,querySelectorAll:s=>s==='.chg-check'?checks:[]},
    alert(){},confirm:()=>true,setTimeout(){},fetch:async(url,options={})=>{let body=options.body;
      if(typeof body==='string')body=JSON.parse(body);calls.push({url,body,method:options.method});
      let value=[];
      if(url==='/api/jobs')value=context.jobsResponse||[];
      else if(url.endsWith('/cover-upload'))value={cover_id:'cover-token'};
      else if(url==='/api/preferences')value=options.method?body:{country:'JP',recurse:false,only_empty:true,fill_lyrics:true,rename:true,include_ids:true,artist_name_preference:'latin',cover_max_px:500};
      else if(url==='/api/scan')value={job_id:'scan'};
      else if(url.endsWith('/save'))value={saved:0,skipped:body.paths.length,failed:0,partial:0,results:body.paths.map(path=>({path,status:'skipped'}))};
      return {ok:true,text:async()=>JSON.stringify(value)};
    }});
  vm.runInContext(script,context);
  return {$,calls,context,documentEvents,run:code=>vm.runInContext(code,context)};
}
function click(button,h){let stopped=false;const event={target:button,stopPropagation(){stopped=true;}};button.onclick(event);if(!stopped)h.documentEvents.click(event);return stopped;}
function row(h,title){return h.$('folderOptions').children.find(r=>r.children.at(-1).title===title);}
(async()=>{
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
  h.run('confirmFolder()');assert.equal(h.$('subPath').value,'Album/Disc2');
  assert.equal(h.$('folderMenu').hidden,true);assert(!h.$('folderToggle').textContent.includes('(임시)'));
  h.documentEvents.click({target:{}});assert.equal(h.$('folderMenu').hidden,true);
  h.$('folderToggle').onclick();assert(row(h,'Album/Disc1/Bonus'));
  h.$('folderToggle').onclick();assert.equal(h.$('folderMenu').hidden,true);
  h.$('folderToggle').onclick();h.$('folderSearch').value='Bonus';h.run('renderFolders()');assert(row(h,'Album/Disc1/Bonus'));
  h.$('folderSearch').value='';h.run('renderFolders()');assert(row(h,'Album/Disc1/Bonus'));
  const reloaded=harness();reloaded.run("musicFolders=['Album','Album/Disc1','Album/Disc1/Bonus'];renderFolders()");
  assert(row(reloaded,'Album/Disc1/Bonus'));
  await h.run('loadPreferences()');assert.equal(h.$('recurse').checked,false);assert.equal(h.$('renameFiles').checked,true);
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
  await h.run('applyCoverToAll()');assert.equal(h.run('currentResults[1]._coverId'),'cover-token');
  const item=h.run('saveItem(currentResults[1])');assert.equal(item.cover_id,'cover-token');assert.equal(item.include_ids,true);
  h.$('onlyEmpty').checked=false;
  h.context.candidate={id:'latin',title:'Song',artist:'原文',artist_latin:'Latin',albumartist:'原文',album_artist_latin:'Latin'};
  h.run('applyCandidate(editingResult,candidate)');assert.equal(h.$('chg_artist').value,'Latin');assert.equal(h.$('chg_albumartist').value,'Latin');
  const confirmedSave=h.run('saveCurrent()');h.run('resolveAction(true)');await confirmedSave;assert.equal(h.calls.at(-1).body.rename,true);
  assert.equal(h.calls.at(-1).body.only_empty,false);assert.equal(h.calls.at(-1).body.fill_lyrics,false);assert.equal(h.calls.at(-1).body.cover_max_px,500);
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
  safety.run("pendingFolder='Album';confirmFolder()");
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
  safety.run('reportSave(report)');assert.equal(safety.$('saveResultDialog').open,true);
  assert.match(safety.$('saveResultCounts').innerHTML,/저장: 2/);
  assert.match(safety.$('saveResultCounts').innerHTML,/일부 처리: 1/);
  assert.match(safety.$('saveResultIssues').innerHTML,/&lt;script&gt;/);
  assert(!safety.$('saveResultIssues').innerHTML.includes('<script>'));
  assert.match(safety.$('saveResultIssues').innerHTML,/warning \/ rename error/);
  assert.equal(safety.$('saveResultState').textContent,'state error');
  assert(html.includes('overflow-wrap:anywhere'));assert(html.includes('max-height:280px;overflow:auto'));
  safety.$('fileFilter').value='a.mp3';safety.run('applyFilter();persistView()');
  const reload=harness();reload.context.jobsResponse=[{id:'other',sub_path:'Other',results:[]},safety.context.job];
  await reload.run('pollJobs()');assert.equal(reload.$('subPath').value,'Album');
  assert.equal(reload.$('folderToggle').textContent,'Album ▼');
  assert.equal(reload.run('displayedJobId'),'folder-job');assert.equal(reload.run('editingResult.path'),'Album/a.mp3');
  assert.equal(reload.$('fileFilter').value,'a.mp3');
  reload.run("pendingFolder='Unscanned';confirmFolder()");assert.equal(reload.run('currentResults.length'),0);
  const emptyReload=harness();emptyReload.context.jobsResponse=reload.context.jobsResponse;
  await emptyReload.run('pollJobs()');assert.equal(emptyReload.$('subPath').value,'Unscanned');
  assert.equal(emptyReload.run('currentResults.length'),0);assert.equal(emptyReload.run('editingResult'),null);
  const optionHarness=harness();
  optionHarness.context.optionJob={id:'options',results:[{path:'one.mp3',original:{title:'Old',revision:'a'.repeat(64)},candidates:[]}]};
  optionHarness.$('fileFilter').value='';optionHarness.run('adoptJob(optionJob)');
  for(const enabled of [true,false]){
    for(const id of ['onlyEmpty','fillLyrics','renameFiles','includeIds'])optionHarness.$(id).checked=enabled;
    optionHarness.$('coverMax').value=enabled?100:1000;
    const pending=optionHarness.run('saveCurrent()');optionHarness.run('resolveAction(true)');await pending;
    const body=optionHarness.calls.at(-1).body;
    assert.equal(body.only_empty,enabled);assert.equal(body.fill_lyrics,enabled);assert.equal(body.rename,enabled);
    assert.equal(body.items[0].include_ids,enabled);assert.equal(body.cover_max_px,enabled?100:1000);
  }
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
  for(const token of html.split('<script>')[0].matchAll(/<\/?([a-z][\w-]*)\b([^>]*)>/gi)){
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
  console.log('PASS: temporary/confirmed folder selection; persistent tree; modal apply/cancel/Escape/validation/remember; control order, centered full-width grid and aligned panels; P2 handlers preserved.');
})().catch(e=>{console.error(e);process.exitCode=1;});
