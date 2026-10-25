// Search, scanning, jobs, folders, sorting and file selection.
// Definitions only; shared state and ordered startup live in app.js.

function formatScanDuration(seconds){const value=Math.max(0,Number(seconds)||0),minutes=Math.floor(value/60);return (minutes?minutes+'분 ':'')+(value-minutes*60).toFixed(2)+'초';}

function scanElapsed(job){const timing=scanBrowserTimes.get(job.id);return timing?.finished!==undefined?timing.finished:Number(job.scan_elapsed_seconds)||0;}

function scanCompletionText(job){return `${job.scanned||0}곡 스캔 완료${job.scan_elapsed_seconds!==undefined?' · '+formatScanDuration(scanElapsed(job)):''}`;}

function observeScanCompletion(job){
  const timing=scanBrowserTimes.get(job.id);
  if(!timing||!['done','cancelled','interrupted','failed'].includes(job.status)||timing.pending||timing.finished!==undefined)return;
  timing.pending=true;
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
    timing.finished=timing.base+(performance.now()-timing.start)/1000;
    console.info('scan_timing',JSON.stringify({job_id:job.id,server_seconds:job.scan_elapsed_seconds,browser_seconds:timing.finished,status:job.status}));
    if(currentJobId===job.id&&job.status==='done'){
      $('progressText').textContent=scanCompletionText(job);
      $('progressText').dataset.serverSeconds=String(job.scan_elapsed_seconds);
      $('progressText').dataset.browserSeconds=String(timing.finished);
    }
  }));
}

function jobViewKey(j){return JSON.stringify([j.id,j.record_version,j.view_revision,j.status,j.scanned,j.total,j.current_file]);}

function scanJobBusy(j){return ['queued','scanning','cancelling'].includes(j.status)||lastSaveTasks.some(t=>t.job_id===j.id&&['queued','saving'].includes(t.status));}

function backgroundChoices(){return [...allJobs.map(j=>({key:'scan:'+j.id,active:scanJobBusy(j)})),...lastSaveTasks.map(j=>({key:'save:'+j.id,active:['queued','saving'].includes(j.status)}))];}

function updateBackgroundSelection(){const choices=backgroundChoices();for(const key of selectedBackgroundJobs){if(!choices.some(c=>c.key===key&&!c.active))selectedBackgroundJobs.delete(key);}document.querySelectorAll('[data-job-select]').forEach(c=>{const item=choices.find(j=>j.key===c.dataset.jobSelect);c.disabled=!item||item.active;c.checked=selectedBackgroundJobs.has(c.dataset.jobSelect);});$('jobSelectedCount').textContent='선택 '+selectedBackgroundJobs.size+'건';$('deleteSelectedJobs').textContent='선택 작업 삭제 ('+selectedBackgroundJobs.size+'건)';$('deleteSelectedJobs').disabled=!selectedBackgroundJobs.size;}

function toggleBackgroundJob(key,checked){if(!backgroundChoices().some(c=>c.key===key&&!c.active))return;if(checked)selectedBackgroundJobs.add(key);else selectedBackgroundJobs.delete(key);updateBackgroundSelection();}

function selectBackgroundJobs(checked){selectedBackgroundJobs.clear();if(checked)backgroundChoices().filter(c=>!c.active).forEach(c=>selectedBackgroundJobs.add(c.key));document.querySelectorAll('[data-job-select]').forEach(c=>c.checked=selectedBackgroundJobs.has(c.dataset.jobSelect));updateBackgroundSelection();}

async function removeBackgroundJobs(keys){if(!keys.length)return;const chosen=backgroundChoices();if(keys.some(key=>!chosen.some(c=>c.key===key&&!c.active)))return alert('진행 중이거나 없는 작업은 삭제할 수 없습니다');if(!await confirmAction('작업 기록 삭제',keys.length+'건의 작업 기록만 삭제할까요?\n음악 파일과 최초 원본 백업은 유지됩니다.','삭제 실행','취소'))return;try{const scans=keys.filter(k=>k.startsWith('scan:')).map(k=>k.slice(5));if(scans.length)await api('/api/jobs/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:scans})});for(const key of keys.filter(k=>k.startsWith('save:')))await api('/api/save-tasks/'+encodeURIComponent(key.slice(5)),{method:'DELETE'});keys.forEach(k=>selectedBackgroundJobs.delete(k));allJobs=allJobs.filter(j=>!scans.includes(j.id));lastSaveTasks=lastSaveTasks.filter(j=>!keys.includes('save:'+j.id));if(scans.includes(currentJobId))clearFolderResults();updateBackgroundSelection();await pollJobs();await refreshSaveTasks();}catch(e){alert('삭제 실패: '+e.message);await pollJobs();await refreshSaveTasks();}}

async function deleteSelectedBackgroundJobs(){return removeBackgroundJobs([...selectedBackgroundJobs]);}

function adoptJob(job){
  captureCurrent();const selectedPath=editingResult?.path;
  if(displayedJobId!==job.id)stopMediaPrefetch();mediaJobStatus=job.status;
  if(displayedJobId!==job.id)$('fileListScroller').scrollTop=0;
  if(displayedJobId)draftJobs.set(displayedJobId,currentResults);
  const previous=new Map((displayedJobId===job.id?currentResults:draftJobs.get(job.id)||[]).map(r=>[r.path,r]));
  currentResults=(job.results||[]).map(r=>{const old=previous.get(r.path);if(old&&old.search_phase&&['waiting','running'].includes(old.search_phase)&&r.search_phase==='complete'&&!old._dirty&&old._selection==='none')old._draft=null;if(old)Object.keys(old).filter(k=>k.startsWith('_')&&(k==='_checked'||k==='_displayOrder'||old._draftRevision===r.original?.revision)).forEach(k=>r[k]=old[k]);return r;});
  let nextOrder=currentResults.reduce((max,r)=>Math.max(max,r._displayOrder??-1),-1)+1;currentResults.forEach(r=>{if(r._displayOrder==null)r._displayOrder=nextOrder++;});
  if(typeof job.sub_path==='string'){$('subPath').value=job.sub_path;pendingFolder=job.sub_path;folderLabel();}
  currentJobId=job.id;displayedJobId=job.id;lastJobSignature=jobSignature(job);editingResult=null;selectedFileIdx=-1;applyFilter();
  const index=filteredResults.findIndex(r=>r.path===selectedPath);if(index>=0)selectFile(index);persistView();
}

function jobSignature(job){return JSON.stringify((job.results||[]).map(r=>[r.path,r.original?.revision,r.search_phase,r.search_generation,r.last_save,r.search_status,r.error,(r.candidates||[]).map(c=>c.id)]));}

function folderLabel(){const pending=pendingFolder!==$('subPath').value;const label=(pendingFolder||'전체')+(pending?' (임시)':'');$('folderToggle').textContent=label+' ▼';$('folderToggle').setAttribute('aria-label',label);}

async function confirmFolder(event){
  event?.stopPropagation();if(pendingFolder!==$('subPath').value&&!await allowDraftMove())return;captureCurrent();$('subPath').value=pendingFolder;folderLabel();closeFolderMenu();
  const matching=allJobs.find(j=>(j.sub_path||'')===pendingFolder);
  if(matching)await loadJob(matching.id);else clearFolderResults();persistView();
}

function readView(){try{const v=JSON.parse(localStorage.getItem('musicFolderView')||'null');return v&&typeof v.folder==='string'?v:null;}catch(e){return null;}}

function persistView(){
  viewPinned=true;try{localStorage.setItem('musicFolderView',JSON.stringify({folder:$('subPath').value,jobId:currentJobId,filter:$('fileFilter').value,selectedPath:editingResult?.path||null}));}catch(e){}
}

function clearFolderResults(){
  if(displayedJobId)draftJobs.set(displayedJobId,currentResults);
  stopMediaPrefetch();mediaJobStatus=null;currentJobId=null;displayedJobId=null;currentResults=[];editingResult=null;selectedFileIdx=-1;lastJobSignature='';
  applyFilter();tagFields.forEach(f=>{$('cur_'+f).textContent='';$('chg_'+f).value='';$('chg_'+f).style.backgroundColor='';});
  $('currentCover').textContent='no image';$('changeCover').textContent='no image';$('candBody').innerHTML='<tr><td colspan="8">이 폴더의 스캔 기록이 없습니다.</td></tr>';
  $('lyricStatus').textContent='없음';$('lyricStatus').onclick=null;$('progBar').style.width='0%';$('progressText').textContent='';$('statusLine').textContent='선택한 폴더의 스캔 기록이 없습니다';
  $('btnResume').style.display='none';
}

function persistExpansion(){try{localStorage.setItem('musicFolderExpansion',JSON.stringify([...expandedFolders]));}catch(e){}}

function closeFolderMenu(){ $('folderMenu').hidden=true; $('folderToggle').setAttribute('aria-expanded','false'); }

function renderFolders(){
  const q=$('folderSearch').value.trim().toLowerCase();
  const box=$('folderOptions'); box.replaceChildren();
  const visible=new Set(['']);
  const children=new Set();
  musicFolders.forEach(path=>{
    const parts=path.split('/');
    for(let i=1;i<parts.length;i++) children.add(parts.slice(0,i).join('/'));
    if(q&&path.toLowerCase().includes(q)){
      for(let i=1;i<=parts.length;i++) visible.add(parts.slice(0,i).join('/'));
    }
  });
  const paths=['',...musicFolders.filter(path=>{
    if(q) return visible.has(path);
    const parts=path.split('/');
    return parts.slice(0,-1).every((_,i)=>expandedFolders.has(parts.slice(0,i+1).join('/')));
  })];
  paths.forEach(path=>{
    const depth=path?path.split('/').length-1:0;
    const row=document.createElement('div'); row.style.cssText='display:flex;align-items:center;margin-top:4px;padding-left:'+depth*14+'px';
    if(children.has(path)){
      const toggle=document.createElement('button'); toggle.type='button'; toggle.className='btn';
      toggle.style.cssText='padding:3px;width:24px;flex-shrink:0';
      const open=!!q||expandedFolders.has(path);
      toggle.textContent=open?'▼':'▶'; toggle.setAttribute('aria-expanded',String(open));
      toggle.setAttribute('aria-label',path+(open?' 접기':' 펼치기')); toggle.disabled=!!q;
      toggle.onclick=e=>{ e.stopPropagation(); const scroll=box.scrollTop; if(expandedFolders.has(path)) expandedFolders.delete(path); else expandedFolders.add(path); persistExpansion(); renderFolders(); box.scrollTop=scroll; };
      row.appendChild(toggle);
    }else{
      const spacer=document.createElement('span'); spacer.style.cssText='width:24px;flex-shrink:0'; row.appendChild(spacer);
    }
    const option=document.createElement('button'); option.type='button'; option.className='btn';
    option.style.cssText='flex:1;min-width:0;text-align:left;overflow-wrap:anywhere';
    option.textContent=path?path.split('/').pop():'전체'; option.title=path||'전체';
    option.setAttribute('aria-pressed',String(path===pendingFolder));
    if(path===pendingFolder)option.style.borderColor='var(--blue)';
    option.onclick=e=>{ e.stopPropagation(); const scroll=box.scrollTop;pendingFolder=path;folderLabel();renderFolders();box.scrollTop=scroll; };
    row.appendChild(option); box.appendChild(row);
  });
}

async function loadFolders(){
  $('folderStatus').textContent='폴더 목록 불러오는 중…';
  renderFolders();
  try{ const data=await api('/api/folders'); musicFolders=data.folders; renderFolders(); $('folderStatus').textContent=''; }
  catch(e){ $('folderStatus').textContent='폴더 목록을 불러오지 못했습니다: '+e.message; }
}

async function startScan(force=false){
  if(actionResolver)return;
  const sub=$('subPath').value.trim();
  if(!sub&&!await confirmAction('전체 음악 스캔', '전체를 선택했습니다. 음악 파일이 약 8만 개이므로 전체 스캔에 매우 오랜 시간이 걸릴 수 있습니다.\n전체 스캔을 시작할까요?', '전체 스캔 시작'))return;
  if(sub!==$('subPath').value.trim())return;
  const payload={sub_path:sub,paths:$('scanPaths').value.split('\n').map(p=>p.trim()).filter(Boolean),recurse:$('recurse').checked,only_empty:$('onlyEmpty').checked,fill_lyrics:$('fillLyrics').checked,rename:$('renameFiles').checked,country:$('searchCountry').value||null,use_fingerprint:$('useFingerprint').checked,force};
  stopMediaPrefetch();mediaJobStatus="scanning";const browserStart=performance.now();
  try{$('btnScan').disabled=true;const res=await api('/api/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});currentJobId=res.job_id;scanBrowserTimes.set(currentJobId,{start:browserStart,base:0});persistView();pollJobs();}catch(e){if(e.status===409&&e.detail){alert(e.detail.message||'백그라운드 작업 목록에서 스캔을 중지해 주세요')}else alert(e.message)}finally{$('btnScan').disabled=false}
}

async function resumeScan(){if(!currentJobId)return;stopMediaPrefetch();mediaJobStatus="scanning";const id=currentJobId,previous=allJobs.find(j=>j.id===id),base=previous?scanElapsed(previous):0,start=performance.now();await api('/api/jobs/'+id+'/resume',{method:'POST'});scanBrowserTimes.set(id,{start,base});pollJobs();}

function renderSaveTasks(tasks){
  lastSaveTasks=tasks;updateBackgroundSelection();
  const box=$('saveJobs');box.innerHTML='';
  tasks.forEach(task=>{
    const active=['queued','saving'].includes(task.status),pct=task.total?Math.round(task.processed/task.total*100):0;
    const label=task.status==='done'?'저장 완료':task.status==='failed'?'저장 중단':task.status==='queued'?'저장 대기':'저장 중';
    const counts=[task.failed?`실패 ${task.failed}개`:'',task.skipped?`건너뜀 ${task.skipped}개`:'',task.partial?`일부 처리 ${task.partial}개`:''].filter(Boolean).join(' · ');
    const row=document.createElement('div');row.className='job';
    row.innerHTML=`<div style="display:flex;justify-content:space-between;font-weight:700"><span class="job-title"><input type="checkbox" data-job-select="save:${esc(task.id)}" ${active?'disabled':''} ${selectedBackgroundJobs.has('save:'+task.id)?'checked':''} aria-label="저장 작업 선택" onchange="toggleBackgroundJob('save:${task.id}',this.checked)"> [${task.saved}/${task.total}] ${esc(task.sub_path||'전체')}</span><span class="badge ${task.status==='done'&&!task.failed?'badge-ok':task.failed||task.status==='failed'?'badge-warn':''}">${label}</span></div><div class="save-current-file" title="${esc(task.current_path||'')}">${esc(task.current_file||task.error||'')}</div><div>${esc(counts)}</div><div class="progress" style="margin-top:4px" title="처리 ${task.processed} / ${task.total}개 파일"><div style="width:${pct}%"></div></div>${active?'':`<div style="display:flex;gap:4px;margin-top:4px"><button class="btn" onclick="loadJob('${task.job_id}')">보기</button><button class="btn btn-red" onclick="deleteSaveTask('${task.id}')">삭제</button></div>`}`;
    box.appendChild(row);
  });
}

function renderOperationStatus(items){
  operationItems=items;const multiple=items.length>1;
  $('operationStatus').hidden=!items.length;
  $('operationSummary').textContent=multiple?`백그라운드 작업 ${items.length}건 진행 중`:items[0]?.message||'';
  $('operationToggle').title=!multiple&&items[0]?.path?items[0].path:'';
  $('operationToggle').setAttribute('data-multiple',String(multiple));
  $('operationArrow').hidden=!multiple;
  if(!multiple)operationExpanded=false;
  $('operationToggle').setAttribute('aria-expanded',String(operationExpanded));
  $('operationDetails').hidden=!multiple||!operationExpanded;
  $('operationDetails').innerHTML=items.map(item=>`<span class="operation-item">${esc(item.message)}${item.file?`<span class="operation-file" title="${esc(item.path)}">${esc(item.file)}</span>`:''}</span>`).join('');
}

function toggleOperationDetails(){if(operationItems.length<2)return;operationExpanded=!operationExpanded;renderOperationStatus(operationItems);}

async function refreshSaveTasks(){
  await Promise.allSettled([
    api('/api/save-tasks').then(renderSaveTasks),
    api('/api/background-operations').then(value=>renderOperationStatus(value.operations||[])).catch(()=>renderOperationStatus([]))
  ]);
}

async function pollSaveTasks(){await refreshSaveTasks();setTimeout(pollSaveTasks,1500);}

async function deleteSaveTask(id){return removeBackgroundJobs(['save:'+id]);}

async function pollJobs(){
  if(jobsPolling){jobsRefreshRequested=true;return;}jobsPolling=true;const initialSelection=currentJobId;
  try{
    if(!renameBusy)await pollPathChanges();
    const jobs=await api('/api/jobs?summary=true'); allJobs=jobs;updateBackgroundSelection();if(currentJobId!==initialSelection&&displayedJobId)return;
    const box=$('jobs');
    if(!jobs.length){box.innerHTML='<div style="text-align:center;color:#999;padding:8px">작업 없음</div>'}else{
      box.innerHTML='';
      jobs.forEach(j=>{
        const pct=j.total?Math.round(j.scanned/j.total*100):0;
        const d=document.createElement('div'); d.className='job';
        // 중지 버튼 추가: scanning, queued, interrupted 모두에 중지/삭제 제공
        let btns='';
        if(j.status==='scanning'||j.status==='queued'||j.status==='cancelling'){
          btns+=`<button class="btn btn-red" style="padding:2px 6px;font-size:11px" onclick="cancelSpecific('${j.id}')">중지</button>`;
        }else if(j.status==='interrupted'){
          btns+=`<button class="btn btn-green" style="padding:2px 6px;font-size:11px" onclick="resumeSpecific('${j.id}')">이어하기</button>`;
          btns+=`<button class="btn btn-red" style="padding:2px 6px;font-size:11px;margin-left:4px" onclick="cancelSpecific('${j.id}')">중지</button>`;
        }else if(j.status==='cancelled'){
          btns+=`<button class="btn btn-green" style="padding:2px 6px;font-size:11px" onclick="resumeSpecific('${j.id}')">이어하기</button>`;
        }
        if(!['scanning','queued','cancelling'].includes(j.status))btns+=`<button class="btn btn-red" style="padding:2px 6px;font-size:11px" onclick="deleteSpecific('${j.id}')">삭제</button>`;
        btns+=`<button class="btn" style="padding:2px 6px;font-size:11px;margin-left:4px" onclick="loadJob('${j.id}')">보기</button>`;
        d.innerHTML=`<div style="display:flex;justify-content:space-between;font-weight:700"><span class="job-title"><input type="checkbox" data-job-select="scan:${esc(j.id)}" ${scanJobBusy(j)?'disabled':''} ${selectedBackgroundJobs.has('scan:'+j.id)?'checked':''} aria-label="스캔 작업 선택" onchange="toggleBackgroundJob('scan:${j.id}',this.checked)"> [${j.scanned||0}/${j.total||0}] ${esc(j.sub_path||'전체')}</span><span class="badge ${j.status==='done'?'badge-ok':j.status==='cancelled'||j.status==='interrupted'?'badge-warn':''}">${j.status}</span></div><div class="job-current-file" title="${esc(j.current_file||'')}">${esc(j.status==='done'?scanCompletionText(j):(j.current_file||'').split('/').pop())}</div><div class="progress" style="margin-top:4px"><div style="width:${pct}%"></div></div><div style="margin-top:4px;display:flex;gap:4px">${btns}</div>`;
        box.appendChild(d);
      });
    }
    let active=jobs.find(j=>j.id===currentJobId&&(!viewPinned||(j.sub_path||'')===$('subPath').value))||(viewPinned?jobs.find(j=>(j.sub_path||'')===$('subPath').value):jobs.find(j=>j.status==='scanning'||j.status==='queued')||jobs[0]);
    if(active&&!active.results&&!saving&&!searching&&!renameEditor&&!renameBusy&&!actionResolver&&(displayedJobId!==active.id||lastDetailRevision!==jobViewKey(active))){const key=jobViewKey(active),expectedSelection=currentJobId;active=await api('/api/jobs/'+encodeURIComponent(active.id));if(currentJobId!==expectedSelection)return;lastDetailRevision=key;}
    if(active){currentJobId=active.id;const pct=active.total?Math.round(active.scanned/active.total*100):0;$('progBar').style.width=pct+'%';$('progressText').textContent=active.status==='done'?scanCompletionText(active):`전체 ${active.total||0}곡 / 검색 완료 ${active.scanned||0}곡 / 남은 ${Math.max(0,(active.total||0)-(active.scanned||0))}곡 (${active.status})`;if(!searching)$('statusLine').textContent=editingResult?.search_status?searchSummary(editingResult):`${active.status} — ${active.diagnostic||active.error||active.current_file||''}${active.search_wait_seconds?' / API 대기 '+active.search_wait_seconds+'초':''}`;if(['scanning','queued','cancelling'].includes(active.status)){ $('btnResume').style.display='none';}else if(active.status==='cancelled'||active.status==='interrupted'){ $('btnResume').style.display='inline-block';}else{ $('btnResume').style.display='none';}if(!saving&&!searching&&!renameEditor&&!renameBusy&&!actionResolver&&active.results&&(displayedJobId!==active.id||lastJobSignature!==jobSignature(active))){adoptJob(active);if(restoredView?.selectedPath){const idx=filteredResults.findIndex(r=>r.path===restoredView.selectedPath);if(idx>=0)selectFile(idx);}restoredView=null;persistView();}observeScanCompletion(active);mediaJobStatus=active.status;scheduleMediaPrefetch();}else if(displayedJobId||restoredView){clearFolderResults();restoredView=null;persistView();}
  }catch(e){}finally{
  jobsPolling=false;clearTimeout(jobPollTimer);const immediate=jobsRefreshRequested;jobsRefreshRequested=false;jobPollTimer=setTimeout(pollJobs,immediate?0:allJobs.some(j=>j.status==='scanning'||j.status==='queued')?1500:3000);
  }
}

async function cancelSpecific(id){ if(!await confirmAction('작업 중지','이 작업을 중지할까요?','중지 실행','취소')) return; try{await api('/api/jobs/'+id+'/cancel',{method:'POST'});await pollJobs();}catch(e){alert(e.message)} }

async function deleteSpecific(id){return removeBackgroundJobs(['scan:'+id]);}

async function resumeSpecific(id){currentJobId=id;await resumeScan();}

async function loadJob(id){if(saving||renameBusy||renameEditor||actionResolver)return;await pollPathChanges();if(id!==currentJobId&&!await allowDraftMove())return;const job=await api('/api/jobs/'+id);adoptJob(job);}

function sortFiles(column){
  captureCurrent();
  fileSortDirection=fileSortColumn===column?-fileSortDirection:1;fileSortColumn=column;
  sortFileDisplay();renderFileList();persistView();
}

function sortFileDisplay(){
  const selected=filteredResults[selectedFileIdx];
  if(fileSortColumn)currentResults.slice().sort((a,b)=>fileSortColumn==='name'?fileSortDirection*fileNameCompare(a,b):fileSortDirection*(({waiting:0,running:1,auto:2,review:3,error:4,saved:5}[fileState(a)])-({waiting:0,running:1,auto:2,review:3,error:4,saved:5}[fileState(b)]))||fileNameCompare(a,b)).forEach((r,i)=>r._displayOrder=i);
  filteredResults.sort((a,b)=>(a._displayOrder??0)-(b._displayOrder??0));
  selectedFileIdx=selected?filteredResults.indexOf(selected):-1;
  [['name','fileNameHeader','sortFileName','파일명'],['state','fileStateHeader','sortFileState','상태']].forEach(([column,header,button,label])=>{
    const active=fileSortColumn===column;
    $(header).setAttribute('aria-sort',active?(fileSortDirection===1?'ascending':'descending'):'none');
    $(button).textContent=label+(active?(fileSortDirection===1?' ▲':' ▼'):'');
  });
}

function applyFilter(){
  captureCurrent();const selectedPath=editingResult?.path;
  const q=$('fileFilter').value.toLowerCase();filteredResults=currentResults.filter(r=>r._renameVisible||!q||r.path.toLowerCase().includes(q)).sort((a,b)=>(a._displayOrder??0)-(b._displayOrder??0));
  $('fileCount').textContent=filteredResults.length;selectedFileIdx=filteredResults.findIndex(r=>r.path===selectedPath);
  if(selectedFileIdx<0){editingResult=null;if(filteredResults.length)selectedFileIdx=0;}
  renderFileList();if(selectedFileIdx>=0)selectFile(selectedFileIdx);
}

function fileState(r){return r.file_state||(r.last_save?.status==='saved'||r.last_save?.status==='partial'?'saved':r.auto_apply?'auto':'review');}

function sanitizeChecks(){currentResults.forEach(r=>{if(fileState(r)!=='auto')r._checked=false;});}

async function requestSelectFile(idx){
  if(saving||actionResolver)return;
  const r=filteredResults[idx];if(!r||r===editingResult)return;
  if(await allowDraftMove())selectFile(filteredResults.indexOf(r));
}

function renderFileList(){
  const numberWidth=Math.max(30,String(Math.max(1,currentResults.length)).length*8+16);$('fileColumn').style.setProperty('--number-width',numberWidth+'px');
  sanitizeChecks();const body=$('fileBody'),scroller=$('fileListScroller'),scrollTop=scroller.scrollTop,nodes=[],next=new Map();
  filteredResults.forEach((r,i)=>{
    const state=fileState(r),status={waiting:'검색 대기',running:'검색 중',auto:'자동선택',review:'확인필요',saved:'저장완료',error:'검색 오류'}[state];
    const key=r.path,tr=fileRowNodes.get(key)||document.createElement('tr');
    const paint=JSON.stringify([i,state,!!r._checked,r.original?.revision,!!r.original?.has_cover,!!r.original?.has_lyrics]);
    if(tr._filePaint!==paint){
      tr.innerHTML=`<td><input type="checkbox" ${r._checked?'checked':''} ${state==='auto'?'':'disabled'} aria-label="${esc(r.path)} 선택" onclick="event.stopPropagation();toggleCheck(${i})"></td><td>${i+1}</td><td class="file-name-cell" title="${esc(r.path)}"><div class="file-name-content">${audioButton(r.path,i)}${fileMediaIcons(r)}<span class="file-name-text" title="더블클릭하여 파일명 변경" ondblclick="event.stopPropagation();beginFilenameEdit(${i})">${esc(r.path.split('/').pop())}</span></div></td><td><span class="file-state file-state-${state}">${status}</span></td>`;
      tr._filePaint=paint;tr.onclick=()=>requestSelectFile(i);
    }
    tr.className=i===selectedFileIdx?'selected':'';nodes.push(tr);next.set(key,tr);
  });
  for(let i=filteredResults.length;i<13;i++){
    const key='empty:'+i,tr=fileRowNodes.get(key)||document.createElement('tr');
    tr.className='file-empty';tr.setAttribute('aria-hidden','true');if(!tr._filePaint){tr.innerHTML='<td colspan="4"></td>';tr._filePaint='empty';}nodes.push(tr);next.set(key,tr);
  }
  const previous=Array.from(body.children);
  if(previous.length!==nodes.length||previous.some((node,i)=>node!==nodes[i]))body.replaceChildren(...nodes);
  fileRowNodes=next;
  if(fileThumbnailObserver){fileThumbnailObserver.disconnect();document.querySelectorAll('[data-file-thumbnail]').forEach(image=>fileThumbnailObserver.observe(image));}
  updateAudioButtons();updateSavePreview();scroller.scrollTop=scrollTop;scheduleMediaPrefetch();
}

function toggleCheck(i){const r=filteredResults[i];if(r&&fileState(r)==='auto')r._checked=!r._checked;renderFileList();}

function toggleSelectAll(checked){
  const rows=currentResults.filter(r=>fileState(r)==='auto');
  const value=typeof checked==='boolean'?checked:!rows.every(r=>r._checked);
  rows.forEach(r=>r._checked=value);renderFileList();
}

function selectFile(idx){
  captureCurrent();
  if(editingResult)editingResult._lyricsEpoch=(editingResult._lyricsEpoch||0)+1;
  selectedFileIdx=idx; const r=filteredResults[idx];
  if(!r||editingResult?.path!==r.path){previewPath=null;previewRevision=null;}
  renderFileList();
  if(!r){editingResult=null;return;}ensureDraft(r);editingResult=r;
  $('cur_title').textContent=r.original?.title||r.parsed?.title||''; $('cur_artist').textContent=r.original?.artist||r.parsed?.artist||''; $('cur_album').textContent=r.original?.album||''; $('cur_track').textContent=r.original?.tracknumber||''; $('cur_year').textContent=r.original?.date||''; $('cur_genre').textContent=r.original?.genre||'';
  invalidateCandidateCover($('currentCover'));
  $('currentCover').innerHTML=r.original?.has_cover?`<img src="/api/cover/${encodeURIComponent(r.path)}?v=${r.original.revision}" onerror="this.parentElement.textContent='no image'">`:'<span>no image</span>';
  $('cur_title').title=[r.original?.format,r.original?.bitrate?`${r.original.bitrate} kbps`:'',r.original?.sample_rate?`${r.original.sample_rate} Hz`:''].filter(Boolean).join(' / ');
  $('cur_albumartist').textContent=r.original?.albumartist||'';
  tagFields.forEach(f=>$('chg_'+f).value=r._draft[f]);
  document.querySelectorAll('.chg-check').forEach(c=>c.checked=r._fields.includes(c.dataset.field));
  const best=r.candidates?.find(c=>c.id===r._candidateId);
  renderChangeCover(r);
  showLyricsStatus(r);
  if(!searching&&r.search_status)$('statusLine').textContent=searchSummary(r);
  renderCandidates(r);updateSavePreview();persistView();
  if(best&&!r._lyricsEdited)applySelectedLyrics(r,best);
}

function searchSummary(r){
  const labels={matched:'검색 완료',partial:'일부 출처 검색 실패',not_found:'검색 결과 없음',error:'검색 실패',cancelled:'검색 중지'};
  const errors=(r.search_errors||[]).map(e=>e.source+': '+e.message).join(' / ');
  return (labels[r.search_status]||r.search_status||'대기 중')+(r.country?' ['+r.country+']':'')+(errors?' — '+errors:'');
}

async function manualSearch(){
  if(!editingResult)return alert('파일을 선택하세요');if(saving||searching)return;
  captureCurrent();const r=editingResult;let query=$('searchQ').value.trim(),country=$('searchCountry').value||null,mode='text';
  const prefix=query.match(/^@([a-z]{2})\s+/i);if(prefix){country=prefix[1].toUpperCase();query=query.slice(prefix[0].length).trim();}
  if(/^@sound(?:\s|$)/i.test(query)){mode='sound';query=query.replace(/^@sound\s*/i,'');}
  const hadDraft=r._selection==='edit'||r._selection==='manual';const fields=[...r._fields];
  searching=true;$('statusLine').textContent=mode==='sound'?'음향 지문 검색 중…':'재검색 중…';
  try{
    const data=await api('/api/jobs/'+currentJobId+'/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:r.path,query,country,mode,use_fingerprint:mode==='sound',expected_revision:r._draftRevision||null})});
    Object.assign(r,data);r._candidateFeedback=null;r._appliedFields=[];
    if(hadDraft){if(!r.candidates.some(c=>c.id===r._candidateId)){r._candidateId=null;r._selection='edit';}}
    else{r._draft=null;ensureDraft(r);r._fields=fields;}
    editingResult=null;selectFile(filteredResults.indexOf(r));$('statusLine').textContent=searchSummary(r);
  }catch(e){alert('재검색 실패: '+e.message);}finally{searching=false;updateSavePreview();}
}
