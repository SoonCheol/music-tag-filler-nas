// Tag drafts, protection, preview, save, restore and filename changes.
// Definitions only; shared state and ordered startup live in app.js.

function protectedField(r,f){return !!(r&&$('onlyEmpty').checked&&String(originalValues(r)[f]||'').trim());}

function protectedAsset(r,kind){return !!(r&&$('onlyEmpty').checked&&r.original?.[kind==='cover'?'has_cover':'has_lyrics']);}

function effectiveFields(r){return commonTagFields.filter(f=>!protectedField(r,f));}

function syncEditProtection(r){
  document.querySelectorAll('.chg-check').forEach(c=>{c.disabled=!r||!r.original?.revision||protectedField(r,c.dataset.field);c.checked=!!r&&effectiveFields(r).includes(c.dataset.field);});
  tagFields.forEach(f=>{$('chg_'+f).readOnly=!r||!r.original?.revision||protectedField(r,f);if(r&&r._draft)$('chg_'+f).value=protectedField(r,f)?originalValues(r)[f]:r._draft[f];$('chg_'+f).title=protectedField(r,f)?'빈 태그만 채우기: 기존 값 보호':'';});
  $('saveCover').disabled=protectedAsset(r,'cover');$('saveCover').checked=commonSaveCover&&!$('saveCover').disabled;
  $('saveLyrics').disabled=protectedAsset(r,'lyrics');$('saveLyrics').checked=commonSaveLyrics&&!$('saveLyrics').disabled;
}

function originalValues(r){const o=r.original||{};return {title:o.title||'',artist:o.artist||'',album:o.album||'',albumartist:o.albumartist||'',track:o.tracknumber||'',year:o.date||'',genre:o.genre||''};}

function candidateValues(c){
  if(!c)return {};
  return $('artistPreference').value==='latin'?{...c,artist:c.artist_latin||c.artist,albumartist:c.album_artist_latin||c.albumartist}:{...c};
}

function draftSignature(r){return JSON.stringify([r._draft,r._candidateId||null,r._coverId||null,r._lyricsEdited?r._lyricsDraft:null]);}

function manualCoverDraft(r,coverId=undefined,jobId=currentJobId){
  // Keep only uploaded asset identifiers, scoped to the exact file revision.
  try{
    const key=JSON.stringify([jobId,r.path,r.original?.revision]),items=new Map(JSON.parse(localStorage.getItem('musicManualCoverDrafts')||'[]'));
    if(coverId===undefined)return items.get(key)||null;
    items.delete(key);if(coverId)items.set(key,coverId);
    localStorage.setItem('musicManualCoverDrafts',JSON.stringify([...items].slice(-128)));
  }catch(e){}return null;
}

function ensureDraft(r){
  r._fields=effectiveFields(r);
  if(r._draft)return;
  r._draft=originalValues(r);r._manualFields=[];r._fields=effectiveFields(r);r._draftRevision=r.original?.revision||'';
  const best=r.auto_apply?r.best:null;r._candidateId=best?.id||null;r._selection=best?'auto':'none';
  if(best){const values=candidateValues(best);tagFields.forEach(f=>{if(values[f]&&!protectedField(r,f))r._draft[f]=String(values[f]);});}
  r._draftBaseline=draftSignature(r);
  const coverId=manualCoverDraft(r);if(coverId){r._coverId=coverId;r._dirty=true;}
}

function captureCurrent(){
  if(!$("saveCover").disabled)commonSaveCover=$("saveCover").checked;
  if(!$("saveLyrics").disabled)commonSaveLyrics=$("saveLyrics").checked;
  if(!editingResult)return;ensureDraft(editingResult);tagFields.forEach(f=>{if(!protectedField(editingResult,f)&&!$('chg_'+f).readOnly)editingResult._draft[f]=$('chg_'+f).value;});
}

function resetDraft(r){
  manualCoverDraft(r,null);
  r._draft=null;r._dirty=false;r._artistIdEdited=false;r._albumArtistIdEdited=false;r._manualArtistId=undefined;r._manualAlbumArtistId=undefined;r._manualFields=[];r._candidateId=null;r._coverId=null;r._lyricsSearch=null;r._lyricsEdited=false;r._lyricsDraft=null;r._lyricsEpoch=(r._lyricsEpoch||0)+1;r._candidateFeedback=null;r._appliedFields=[];r._manualLyricsStatus=null;
  ensureDraft(r);previewPath=null;previewRevision=null;
  if(editingResult===r)tagFields.forEach(f=>$('chg_'+f).value=r._draft[f]);
}

async function allowDraftMove(){
  captureCurrent();if(!editingResult?._dirty||draftSignature(editingResult)===editingResult._draftBaseline)return true;
  const r=editingResult;
  if(!await confirmAction('미저장 변경사항','현재 곡의 수정 내용을 버리고 이동할까요?','버리고 이동','계속 편집'))return false;
  resetDraft(r);return true;
}

function applyPathChange(change){
  captureCurrent();const old=change.old_path,next=change.new_path,scroll=$('fileListScroller').scrollTop;
  stopRenamedAudio(old);
  if(renameEditor?.path===old&&!renameBusy)cancelFilenameEdit();
  const visible=filteredResults.some(r=>r.path===old);
  const groups=[currentResults,...draftJobs.values(),...allJobs.map(j=>j.results||[])];
  groups.forEach(rows=>rows.forEach(r=>{
    if(r.path!==old||r.original?.revision!==change.revision)return;
    r.path=next;if(visible&&currentResults.includes(r))r._renameVisible=true;
    if(r._lyricsSearch?.choices)r._lyricsSearch.choices=r._lyricsSearch.choices.map(c=>({...c,lyrics_id:(change.lyrics_tokens||[]).find(t=>t.old_id===c.lyrics_id)?.new_id||c.lyrics_id}));
    const token=r._lyricsSearch?.lyrics_id,remap=(change.lyrics_tokens||[]).find(t=>t.old_id===token);
    if(remap)r._lyricsSearch.lyrics_id=remap.new_id;
    else if(token)r._lyricsSearch.lyrics_id=null;
  }));
  if(previewPath===old)previewPath=next;
  if(restoredView?.selectedPath===old)restoredView.selectedPath=next;
  const saved=readView();if(saved?.selectedPath===old){saved.selectedPath=next;try{localStorage.setItem('musicFolderView',JSON.stringify(saved));}catch(e){}}
  const node=fileRowNodes.get(old);if(node){fileRowNodes.delete(old);delete node._filePaint;fileRowNodes.set(next,node);}
  const lyricKey=JSON.stringify([old,change.revision]),cached=storedLyricsCache.get(lyricKey);
  if(cached){storedLyricsCache.delete(lyricKey);storedLyricsCache.set(JSON.stringify([next,change.revision]),cached);}
  hideHoverCover();candidateCoverCache.clear();
  if(!renameEditor){applyFilter();if(selectedFileIdx>=0)selectFile(selectedFileIdx);}
  $('fileListScroller').scrollTop=scroll;persistView();
}

async function pollPathChanges(){
  const response=await api('/api/path-changes?after='+pathChangeCursor);
  for(const change of response.changes||[]){applyPathChange(change);pathChangeCursor=Math.max(pathChangeCursor,change.seq);}
}

function cancelFilenameEdit(){
  if(renameBusy||!renameEditor)return;
  renameEditor=null;const scroll=$('fileListScroller').scrollTop;
  fileRowNodes.forEach(node=>delete node._filePaint);renderFileList();$('fileListScroller').scrollTop=scroll;
}

function beginFilenameEdit(index){
  if(renameBusy||renameEditor||saving||searching||actionResolver)return;
  const r=filteredResults[index];if(!r)return;
  captureCurrent();const node=fileRowNodes.get(r.path),span=node?.querySelector('.file-name-text');if(!span)return;
  const name=r.path.split('/').pop(),dot=name.lastIndexOf('.'),input=document.createElement('input');
  input.className='input filename-editor';input.value=name.slice(0,dot);input.setAttribute('aria-label','새 파일명 (확장자 제외)');
  renameEditor={r,path:r.path,jobId:currentJobId,stem:input.value,input};
  input.onclick=e=>e.stopPropagation();input.ondblclick=e=>e.stopPropagation();
  input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();e.stopPropagation();submitFilenameEdit();}else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();cancelFilenameEdit();}};
  input.onblur=()=>{if(!renameBusy)cancelFilenameEdit();};span.replaceWith(input);input.focus();input.select();
}

async function submitFilenameEdit(){
  const edit=renameEditor;if(!edit||renameBusy)return;
  const stem=edit.input.value;if(stem===edit.stem){cancelFilenameEdit();return;}
  renameBusy=true;edit.input.disabled=true;stopRenamedAudio(edit.path);
  try{
    const result=await api('/api/jobs/'+encodeURIComponent(edit.jobId)+'/rename',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:edit.path,stem,expected_revision:edit.r.original.revision})});
    renameEditor=null;if(result.change)applyPathChange(result.change);else renderFileList();
    $('statusLine').textContent='파일명 변경 완료';
  }catch(error){renameEditor=null;fileRowNodes.forEach(node=>delete node._filePaint);renderFileList();$('statusLine').textContent='파일명 변경 실패: '+error.message;alert('파일명 변경 실패: '+error.message);}
  finally{renameBusy=false;}
}

function applyCandidate(r,c){
  ensureDraft(r);captureCurrent();const base=originalValues(r),before={...r._draft},beforeCover=$('changeCover').innerHTML;
  const values=candidateValues(c);
  const offered=tagFields.filter(f=>values[f]);
  const blocked=offered.filter(f=>$('onlyEmpty').checked&&base[f]);
  tagFields.forEach(f=>{if(protectedField(r,f))base[f]=before[f];else if(values[f])base[f]=String(values[f]);});
  const changed=tagFields.filter(f=>String(before[f]||'')!==String(base[f]||''));
  r._draft=base;r._dirty=true;r._manualFields=[];r._candidateId=c.id;r._selection='manual';r._appliedFields=changed;
  tagFields.forEach(f=>$('chg_'+f).value=base[f]);
  const url=candidateCoverUrl(c,r),coverAllowed=$('saveCover').checked&&url&&!($('onlyEmpty').checked&&r.original?.has_cover);
  renderChangeCover(r);
  r._candidateFeedback=null;
  r._lyricsEpoch=(r._lyricsEpoch||0)+1;
  updateSavePreview();applySelectedLyrics(r,c);
}

function toggleTagPreview(){
  if(!editingResult||saving||searching)return;
  captureCurrent();
  if(previewPath===editingResult.path){previewPath=null;previewRevision=null;}
  else{previewPath=editingResult.path;previewRevision=editingResult.original?.revision;}
  updateSavePreview();
}

function renderTagPreview(r){
  if(!r||previewPath!==r.path||previewRevision!==r.original?.revision){previewPath=null;previewRevision=null;}
  const active=!!r&&previewPath===r.path;
  $('btnApplyCandidate').textContent=active?'미리보기 취소':'미리보기';
  $('btnApplyCandidate').disabled=!r||saving||searching;
  $('btnApplyCandidate').setAttribute('aria-pressed',String(active));
  $('tagPreviewLabel').hidden=!active;$('tagPreviewNote').hidden=!active;
  const base=r?originalValues(r):Object.fromEntries(tagFields.map(f=>[f,'']));
  const plan=active?plannedChanges(r):null;
  const candidate=r?.candidates?.find(c=>c.id===r._candidateId);
  renderLyricsPanels(r,active,plan);
  tagFields.forEach(f=>{
    let value=base[f];
    const changed=active&&plan.changes.includes(f);
    if(changed)value=String((r._selection==='auto'?candidateValues(candidate)[f]:r._draft[f])||'');
    else if(!active&&r&&(f==='title'||f==='artist'))value=value||r.parsed?.[f]||'';
    $('cur_'+f).textContent=value;$('cur_'+f).style.color=changed?'#c62828':'';
  });
  let html=r?.original?.has_cover?`<img src="/api/cover/${encodeURIComponent(r.path)}?v=${r.original.revision}" onerror="this.parentElement.textContent='no image'">`:'<span>no image</span>';
  if(active&&plan.cover&&!r._coverId&&candidate){paintCandidateCover($('currentCover'),candidate,r);return;}
  invalidateCandidateCover($('currentCover'));
  if(active&&plan.cover){
    const url=r._coverId?`/api/jobs/${encodeURIComponent(currentJobId)}/uploaded-cover/${encodeURIComponent(r._coverId)}`:candidate?candidateCoverUrl(candidate,r):'';
    if(url)html=`<img src="${url}" alt="커버 미리보기 — 저장 시 검증" onerror="this.parentElement.textContent='커버 미리보기 실패'">`;
  }
  if($('currentCover').innerHTML!==html)$('currentCover').innerHTML=html;
}

function toggleAllChange(c){commonTagFields=c?[...tagFields]:[];captureCurrent();updateSavePreview();}

function saveItem(r,allowManualMismatch=false){
  captureCurrent();
  ensureDraft(r);
  if(!r._draftRevision)throw new Error(r.path+': 이전 작업에는 파일 검증값이 없습니다. 다시 스캔하세요.');
  const plan=plannedChanges(r,allowManualMismatch);
  return {path:r.path,expected_revision:r._draftRevision,selection:r._selection,candidate_id:r._candidateId,
    manual_artist_ids:r._artistIdEdited?r._manualArtistId.split(';').filter(Boolean):null,manual_album_artist_ids:r._albumArtistIdEdited?r._manualAlbumArtistId.split(';').filter(Boolean):null,
    values:{...r._draft},fields:[...r._fields],include_cover:commonSaveCover&&!protectedAsset(r,'cover')&&(!!r._coverId||(!!r._candidateId&&hasCandidateCoverSource(r))),cover_id:commonSaveCover&&!protectedAsset(r,'cover')?r._coverId||null:null,include_ids:$('includeIds').checked||r._artistIdEdited||r._albumArtistIdEdited,lyrics_id:lyricChoice(r,allowManualMismatch)?.lyrics_id||null,lyrics_text:r._lyricsEdited?plan.lyrics_text:null,approve_manual_lyrics_mismatch:false,_plan:plan};
}

let saveConfirmResolver=null;
function resolveSaveConfirm(accepted){const resolve=saveConfirmResolver;saveConfirmResolver=null;$('saveConfirmDialog').close();if(resolve)resolve(accepted);}
function saveConfirm(title,bodyHtml,acceptLabel){
  if(saveConfirmResolver)return Promise.resolve(false);
  $('saveConfirmTitle').textContent=title;$('saveConfirmBody').innerHTML=bodyHtml;$('saveConfirmAccept').textContent=acceptLabel;$('saveConfirmCancel').textContent='취소';
  return new Promise(resolve=>{saveConfirmResolver=resolve;$('saveConfirmDialog').showModal();$('saveConfirmCancel').focus();});
}
function finalSaveTags(r){const base=originalValues(r),candidate=r.candidates?.find(c=>c.id===r._candidateId),active=r._selection!=='none';tagFields.forEach(f=>{if(active&&r._fields.includes(f)&&(!$('onlyEmpty').checked||!base[f]))base[f]=String((r._selection==='auto'?candidateValues(candidate)[f]:r._draft[f])||'');});return base;}
function manualMismatch(r){const state=r?._lyricsSearch;if(r?._lyricsEdited||!state?.manual||!state.lyrics_id||state.status!=='found')return [];const query=(()=>{try{const v=JSON.parse(state.queryKey||'[]');return {title:v[0]||'',artist:v[1]||''};}catch{return {title:state.query_title||'',artist:state.query_artist||''};}})(),final=finalSaveTags(r);return [['title','제목'],['artist','가수']].filter(([key])=>String(query[key]||'').trim()!==String(final[key]||'').trim()).map(([key,label])=>({label,saved:final[key]||'',query:query[key]||''}));}
function currentSaveBody(r,item,mismatch){
  const plan=plannedChanges(r,true),fields=[...tagFields.map(f=>({label:fieldLabels[f]||f,on:plan.changes.includes(f)})),{label:'앨범 커버',on:plan.cover},{label:'가사',on:plan.lyrics},{label:'시간 동기화 가사',on:plan.synced},{label:'LRC 파일',on:plan.lrc},{label:'식별자',on:plan.ids}],included=fields.filter(x=>x.on).length;
  let html=`<div class="save-file-name">${esc(r.path)}</div><div class="save-section-heading">저장 항목 <span class="muted">저장 대상 ${included}개 · 저장 제외 ${fields.length-included}개</span></div><div class="save-field-grid">${fields.map(x=>`<div class="save-field ${x.on?'on':'off'}"><span class="mark">${x.on?'◉':'○'}</span>${esc(x.label)}</div>`).join('')}</div>`;
  if(mismatch.length)html+=`<hr class="save-rule"><section class="save-warning"><div class="save-warning-label">⚠ 가사 검색 정보 불일치</div><table class="save-compare"><thead><tr><th>항목</th><th>저장할 태그</th><th>가사 검색어</th></tr></thead><tbody>${mismatch.map(x=>`<tr><td>${esc(x.label)}</td><td>${esc(x.saved)}</td><td>${esc(x.query)}</td></tr>`).join('')}</tbody></table></section>`;
  return html;
}
function selectedSaveBody(rows){const plans=rows.map(r=>plannedChanges(r,false)),tagCount=plans.filter(p=>p.changes.length).length,lyricCount=plans.filter(p=>p.lyrics).length;return `<div class="save-summary"><div class="save-summary-row"><span>저장 대상 음악</span><strong>${rows.length}곡</strong></div><div class="save-summary-row"><span>태그 변경 예상</span><strong>${tagCount}곡</strong></div><div class="save-summary-row"><span>가사 저장 예상</span><strong>${lyricCount}곡</strong></div></div><div class="save-option-lines"><div>빈 태그만 채우기 <strong>${$('onlyEmpty').checked?'켜짐':'꺼짐'}</strong></div><div>가사 저장 <strong>${commonSaveLyrics?'켜짐':'꺼짐'}</strong></div><div>파일명 자동 변경 <strong>비활성화</strong></div></div><p class="save-info">태그 및 가사 수치는 저장 예상치이며, 실제 성공 수는 처리 결과에서 확인할 수 있습니다.</p>`;}
function reportSave(res,scope,rows,plansByPath){
  const results=res.results||[],unchanged=res.unchanged??results.filter(o=>o.reason==='unchanged').length,partial=res.partial??results.filter(o=>o.status==='partial').length,failed=res.failed??results.filter(o=>o.status==='failed').length,saved=res.saved??results.filter(o=>o.status==='saved'||o.status==='partial').length,success=Math.max(0,saved-partial);
  $('saveResultTitle').textContent=scope==='current'?'현재곡 저장 후 확인':'선택곡 저장 후 확인';$('saveResultState').textContent=res.state_error||'';
  if(scope==='current'){
    const o=results[0]||{},status=o.status==='partial'?'partial':o.status==='failed'?'failed':o.reason==='unchanged'?'unchanged':'success',icon=status==='success'?'✔':status==='partial'?'⚠':status==='failed'?'✕':'○';
    $('saveResultHeading').innerHTML=`<div class="save-result-status ${status}"><span>${icon}</span>${status==='success'?'정상적으로 저장되었습니다.':status==='partial'?'일부 항목만 저장되었습니다.':status==='failed'?'저장하지 못했습니다.':'변경된 항목이 없습니다.'}</div>`;
    $('saveResultCounts').innerHTML='';const row=rows[0],plan=row?plansByPath.get(row.path):null,details=[];
    if(plan){const savedFields=o.status==='saved'?plan.changes:(o.saved_fields||[]),failedFields=o.status==='failed'?plan.changes:(o.failed_fields||[]),savedAssets=o.saved_assets||[],failedAssets=o.status==='failed'?['cover','lyrics','synced','lrc','ids']:(o.failed_assets||[]),kind=(key,on)=>!on?'off':savedFields.includes(key)||savedAssets.includes(key)?'on':failedFields.includes(key)||failedAssets.includes(key)?'fail':'off';for(const f of tagFields)details.push({label:fieldLabels[f],kind:kind(f,plan.changes.includes(f))});details.push({label:'앨범 커버',kind:kind('cover',plan.cover)},{label:'가사',kind:kind('lyrics',plan.lyrics)},{label:'시간 동기화 가사',kind:kind('synced',plan.synced)},{label:'LRC 파일',kind:kind('lrc',plan.lrc)},{label:'식별자',kind:kind('ids',plan.ids)});}
    $('saveResultIssues').innerHTML=`<div class="save-section-heading">저장 결과</div><div class="save-field-grid">${details.map(x=>`<div class="save-field ${x.kind}"><span class="mark">${x.kind==='on'?'◉':x.kind==='fail'?'⊗':'○'}</span>${esc(x.label)}</div>`).join('')}</div>${status==='partial'||status==='failed'?`<div class="save-error-detail">${esc([o.message,o.warning,o.rename_error].filter(Boolean).join(' · ')||'서버가 구체적인 실패 원인을 반환하지 않았습니다.')}</div>`:''}`;
  }else{
    $('saveResultHeading').innerHTML=`<div class="save-result-status ${partial||failed?'partial':'success'}"><span>${partial||failed?'⚠':'✔'}</span>${partial||failed?'선택한 곡 처리가 완료되었습니다.':'선택한 모든 곡이 정상적으로 저장되었습니다.'}</div>`;
    $('saveResultCounts').className='save-result-counts';$('saveResultCounts').innerHTML=[['저장 성공',success],['일부 저장',partial],['저장 실패',failed],['변경 없음',unchanged]].map(([label,n])=>`<div class="save-result-count"><label>${label}</label><strong>${n}</strong></div>`).join('');
    const issues=results.filter(o=>o.status==='partial'||o.status==='failed');
    $('saveResultIssues').innerHTML=issues.length?`<div class="save-list-title">문제가 발생한 파일</div><div class="save-result-list">${issues.map(o=>{const r=rows.find(item=>item.path===(o.request_path||o.path)),p=r?plansByPath.get(r.path):null,labels={...fieldLabels,cover:'앨범 커버',lyrics:'가사',synced:'시간 동기화 가사',lrc:'LRC 파일',ids:'식별자'},requested=[...(p?.changes||[]),...(p?.cover?['cover']:[]),...(p?.lyrics?['lyrics']:[]),...(p?.synced?['synced']:[]),...(p?.lrc?['lrc']:[]),...(p?.ids?['ids']:[])],completed=o.status==='partial'?[...(o.saved_fields||[]),...(o.saved_assets||[])]:[...(o.saved_fields||requested.filter(f=>fieldLabels[f])),...(o.saved_assets||[])],problems=o.status==='failed'?requested:[...(o.failed_fields||[]),...(o.failed_assets||[])],reason=[o.message,o.warning,o.rename_error,...(o.postprocess_errors||[]).map(e=>e.message)].filter(Boolean).join(' · ');return `<article class="save-result-item"><div class="save-result-name"><span class="save-filename">${esc(o.path||o.request_path||'파일명 없음')}</span><span class="save-pill ${o.status==='failed'?'failed':''}">${o.status==='partial'?'일부 저장':'저장 실패'}</span></div>${completed.length?`<div class="save-result-line good">✓ 저장 성공: ${esc(completed.map(f=>labels[f]||f).join(', '))}</div>`:''}<div class="save-result-line bad">✕ 저장하지 못한 항목: ${esc(problems.length?problems.map(f=>labels[f]||f).join(', '):'저장 요청 항목')}</div>${reason?`<div class="save-result-reason">원인: ${esc(reason)}</div>`:''}</article>`}).join('')}</div>`:'<p class="save-info">저장에 문제가 발생한 파일이 없습니다.</p>';
  }
  $('saveResultDialog').showModal();
}

async function submitSave(rows,scope,label){
  captureCurrent();if(saving||searching||actionResolver)return;
  const paths=rows.map(r=>r.path);
  if(!paths.length)return alert('저장할 파일이 없습니다');
  let items;try{items=rows.map(r=>saveItem(r,scope==='current'));}catch(e){return alert(e.message);}
  if($('onlyEmpty').checked&&!rows.some(r=>{const p=plannedChanges(r,scope==='current');return p.changes.length||p.cover||p.lyrics||p.synced||p.lrc||p.ids;}))return alert('저장할 빈 태그 항목이 없습니다');
  const jobId=currentJobId;
  const payload={scope,paths,save_cover:commonSaveCover,save_lyrics:commonSaveLyrics,checked_paths:scope==='current'?[]:[...paths],items,only_empty:$('onlyEmpty').checked,fill_lyrics:$('fillLyrics').checked,save_synced:$('saveSynced').checked,create_lrc:$('createLrc').checked,rename:false,cover_max_px:Number($('coverMax').value),artist_name_preference:$('artistPreference').value||'original'};
  const plansByPath=new Map(rows.map(r=>[r.path,plannedChanges(r,scope==='current')])),mismatches=scope==='current'?manualMismatch(rows[0]):[],title=scope==='current'?'현재곡 저장 전 확인':'선택곡 저장 전 확인',body=scope==='current'?currentSaveBody(rows[0],items[0],mismatches):selectedSaveBody(rows),accept=mismatches.length?'확인 후 저장':'저장 실행';
  saving=true;stopMediaPrefetch();updateSavePreview();
  try{
    if(!await saveConfirm(title,body,accept))return;
    if(scope==='current'&&mismatches.length)items[0].approve_manual_lyrics_mismatch=true;
    items.forEach(item=>{delete item._plan;});
    if(currentJobId!==jobId)throw new Error('확인 중 작업이 변경되었습니다. 저장 대상을 다시 확인하세요.');
    const saveRequest=api('/api/jobs/'+jobId+'/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    refreshSaveTasks();
    const res=await saveRequest;refreshSaveTasks();
    res.results.forEach(o=>{const r=currentResults.find(r=>r.path===(o.request_path||o.path));if(!r)return;
      if(o.lyrics_search)r._lyricsSearch={...o.lyrics_search,queryKey:lyricQueryKey(r)};
      if(o.changed&&r._lyricsSearch)r._lyricsSearch.lyrics_id=null;
      r.last_save=o;if(o.file_state)r.file_state=o.file_state;
      if(o.changed){manualCoverDraft(r,null,jobId);r._checked=false;r._dirty=false;r._artistIdEdited=false;r._albumArtistIdEdited=false;r._manualArtistId=undefined;r._manualAlbumArtistId=undefined;}
      if(o.original){r.original=o.original;r.path=o.path;if(o.changed){r._draft=null;r._candidateFeedback=null;r._appliedFields=[];r._coverId=null;if(editingResult===r)editingResult=null;}}
    });
    renderFileList();if(selectedFileIdx>=0)selectFile(selectedFileIdx);reportSave(res,scope,rows,plansByPath);
  }catch(e){alert('저장 요청 실패: '+e.message);}finally{saving=false;updateSavePreview();scheduleMediaPrefetch();pumpCandidateMedia();}
}

async function saveCurrent(){if(!editingResult)return alert('파일을 선택하세요');return submitSave([editingResult],'current','현재 곡');}

function saveTarget(){sanitizeChecks();const rows=currentResults.filter(r=>r._checked&&fileState(r)==='auto');return {rows,scope:'all',label:`작업 전체 저장 (체크 ${rows.length}곡)`};}

async function saveAll(){const target=saveTarget();return submitSave(target.rows,'all','체크한 자동선택');}

async function saveSelected(){return submitSave(saveTarget().rows,'selected','체크한 자동선택');}

function plannedChanges(r,allowManualMismatch=false){
  ensureDraft(r);const base=originalValues(r),active=r._selection!=='none';
  const emptyOnly=$('onlyEmpty').checked;
  const candidate=r.candidates?.find(c=>c.id===r._candidateId);
  const changes=tagFields.filter(f=>active&&r._fields.includes(f)&&(!emptyOnly||!base[f])&&String((r._selection==='auto'?candidateValues(candidate)[f]:r._draft[f])||'')!==String(base[f]));
  const cover=commonSaveCover&&(!emptyOnly||!r.original?.has_cover)&&(!!r._coverId||(active&&!!candidate&&hasCandidateCoverSource(r)));
  const final={...base};changes.forEach(f=>final[f]=String((r._selection==='auto'?candidateValues(candidate)[f]:r._draft[f])||''));
  const lyric=lyricPlan(r,allowManualMismatch),lyrics=lyric.change;
  const timed=!!(lyricChoice(r,allowManualMismatch)?.synced&&commonSaveLyrics&&!protectedAsset(r,'lyrics'));
  return {changes,cover,lyrics,lyrics_text:lyric.text,synced:timed&&$('saveSynced').checked&&!r.original?.has_synced,lrc:timed&&$('createLrc').checked,rename:$('renameFiles').checked,ids:!!((active&&candidate&&$('includeIds').checked)||r._artistIdEdited||r._albumArtistIdEdited)};
}

function planSummary(rows){
  const plans=rows.map(plannedChanges),count=key=>plans.filter(p=>p[key]).length;
  return `텍스트 변경 ${plans.filter(p=>p.changes.length).length}곡 / 커버 적용 시도 ${count('cover')}곡 / 가사 검색 시도 ${count('lyrics')}곡 / 파일명 변경 검사 ${count('rename')}곡 / 식별자 검토 ${count('ids')}곡`;
}

function updateSavePreview(){
  const target=saveTarget(),visible=filteredResults.filter(r=>r._checked).length;
  const hidden=target.rows.length-visible,eligible=currentResults.filter(r=>fileState(r)==='auto');
  $('btnSaveAll').textContent=target.label;$('btnSaveAll').disabled=!target.rows.length||saving||searching;
  $('btnSaveSelected').textContent=`선택 곡 저장 (${target.rows.length}곡)`;$('btnSaveSelected').disabled=!target.rows.length||saving||searching;
  $('selectedInfo').textContent=`체크: 표시 ${visible}곡 / 숨김 ${hidden}곡`;
  $('checkAll').checked=eligible.length>0&&target.rows.length===eligible.length;
  $('checkAll').indeterminate=target.rows.length>0&&target.rows.length<eligible.length;
  $('saveScopeInfo').textContent=`일괄 저장 대상: 체크된 자동선택 ${target.rows.length}곡 (필터 숨김 ${hidden}곡 포함). 작업 전체 저장과 선택 곡 저장은 같은 체크 범위를 사용합니다. 전체선택도 모든 자동선택 곡에만 적용됩니다. `+planSummary(target.rows);
  const r=editingResult&&filteredResults.includes(editingResult)?editingResult:null;
  syncEditProtection(r);
  renderTagPreview(r);
  ['btnSaveCurrent','btnDiscard','btnRestore'].forEach(id=>$(id).disabled=!r||!r.original?.revision||saving||searching);
  $('candidateFeedback').hidden=true;
  $('candidateFeedback').textContent=r?._candidateFeedback||'';
  tagFields.forEach(f=>{$('chg_'+f).style.boxShadow=r?._appliedFields?.includes(f)?'0 0 0 2px var(--blue)':'';});
  if(!r){$('changeSummary').textContent='파일을 선택하면 변경 예정 내용을 표시합니다.';return;}
  const p=plannedChanges(r);
  tagFields.forEach(f=>{$('chg_'+f).style.backgroundColor=p.changes.includes(f)?'var(--blue-light)':'';});
  $('changeSummary').textContent='현재 곡 변경 예정: '+(p.changes.length?p.changes.map(f=>fieldLabels[f]).join(', '):'텍스트 변경 없음')+` · 커버 ${p.cover?'적용 시도':'유지'} · 가사 ${p.lyrics?'검색 시도':'유지'} · 파일명 ${p.rename?'변경 검사':'유지'} · 식별자 ${p.ids?'검토':'유지'}`;
}

async function discardDraft(){
  if(!editingResult||saving||searching)return;
  const r=editingResult,jobId=currentJobId;if(!await confirmAction('미저장 편집 취소','현재 곡의 미저장 편집을 취소할까요? 음악 파일은 변경하지 않습니다.','편집 취소','계속 편집'))return;
  if(editingResult!==r||currentJobId!==jobId||saving||searching)return;
  resetDraft(r);
  editingResult=null;selectFile(selectedFileIdx);
}

async function resetChange(){
  if(!editingResult||saving)return;
  captureCurrent();const r=editingResult;
  if(!r._draftRevision)return alert('파일 검증값이 없습니다. 다시 스캔하세요.');
  if(!await confirmAction('최초 원본 복원',r.path+'\n태그뿐 아니라 파일 전체가 최초 백업 상태로 돌아갑니다.','원본 복원 실행','취소'))return;
  saving=true;try{
    const res=await api('/api/revert/'+encodeURIComponent(r.path),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_revision:r._draftRevision})});
    r.original=res.original;r._draft=null;r._candidateFeedback=null;r._appliedFields=[];editingResult=null;selectFile(selectedFileIdx);
    alert((res.status==='restored'?'원본 복원 완료 (SHA256 일치)':'이미 원본과 같습니다')+(res.state_error?'\n작업 상태 기록 오류: '+res.state_error:''));
  }catch(e){alert('복원 실패: '+e.message);}finally{saving=false;updateSavePreview();scheduleMediaPrefetch();pumpCandidateMedia();}
}
