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

function draftSignature(r){return JSON.stringify([r._draft,r._candidateId||null,r._coverId||null,r._lyricsEdited?r._lyricsSearch?.lyrics:null]);}

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
  r._draft=null;r._dirty=false;r._manualFields=[];r._candidateId=null;r._coverId=null;r._lyricsSearch=null;r._lyricsEdited=false;r._lyricsEpoch=(r._lyricsEpoch||0)+1;r._candidateFeedback=null;r._appliedFields=[];r._manualLyricsStatus=null;
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

function saveItem(r){
  captureCurrent();
  ensureDraft(r);
  if(!r._draftRevision)throw new Error(r.path+': 이전 작업에는 파일 검증값이 없습니다. 다시 스캔하세요.');
  return {path:r.path,expected_revision:r._draftRevision,selection:r._selection,candidate_id:r._candidateId,
    values:{...r._draft},fields:[...r._fields],include_cover:commonSaveCover&&!protectedAsset(r,'cover')&&(!!r._coverId||(!!r._candidateId&&hasCandidateCoverSource(r))),cover_id:commonSaveCover&&!protectedAsset(r,'cover')?r._coverId||null:null,include_ids:$('includeIds').checked,lyrics_id:lyricChoice(r)?.lyrics_id||null,lyrics_text:r._lyricsEdited&&lyricChoice(r)?r._lyricsSearch.lyrics:null};
}

function reportSave(res){
  const unchanged=res.unchanged??(res.results||[]).filter(o=>o.reason==='unchanged').length;
  const unselected=res.unselected??(res.results||[]).filter(o=>o.reason==='no_selection').length;
  $('saveResultCounts').innerHTML=`<span>저장: ${esc(res.saved)}</span><span>변경 없음: ${esc(unchanged)}</span><span>미선택: ${esc(unselected)}</span><span>실패: ${esc(res.failed)}</span><span>일부 처리: ${esc(res.partial)}</span>`;
  $('saveResultState').textContent=res.state_error||'';
  const reasonLabels={no_selection:'후보·수동 편집 미선택',unchanged:'변경 없음'};
  const issues=(res.results||[]).filter(o=>o.status==='failed'||o.status==='partial'||o.message||o.warning||o.rename_error||o.reason);
  $('saveResultIssues').innerHTML=issues.length?issues.map(o=>{
    const reasons=[o.message,o.warning,o.rename_error,o.reason&&(reasonLabels[o.reason]||o.reason)].filter(Boolean);
    const state={failed:'실패',partial:'일부 처리',skipped:'변경 없음·미선택',saved:'저장'}[o.status]||'안내';
    return `<li><strong>${esc(o.path||o.request_path||'파일명 없음')}</strong><div>${esc(state)}: ${esc([...new Set(reasons)].join(' / ')||'상세 사유가 제공되지 않았습니다.')}</div></li>`;
  }).join(''):'<li>문제가 보고된 파일이 없습니다.</li>';
  $('saveResultDialog').showModal();
}

async function submitSave(rows,scope,label){
  captureCurrent();if(saving||searching||actionResolver)return;
  const paths=rows.map(r=>r.path);
  if(!paths.length)return alert('저장할 파일이 없습니다');
  let items;try{items=rows.map(saveItem);}catch(e){return alert(e.message);}
  if($('onlyEmpty').checked&&!rows.some(r=>{const p=plannedChanges(r);return p.changes.length||p.cover||p.lyrics||p.synced||p.lrc;}))return alert('저장할 빈 태그 항목이 없습니다');
  const jobId=currentJobId;
  const payload={scope,paths,save_cover:commonSaveCover,save_lyrics:commonSaveLyrics,checked_paths:scope==='current'?[]:[...paths],items,only_empty:$('onlyEmpty').checked,fill_lyrics:$('fillLyrics').checked,save_synced:$('saveSynced').checked,create_lrc:$('createLrc').checked,rename:$('renameFiles').checked,cover_max_px:Number($('coverMax').value),artist_name_preference:$('artistPreference').value||'original'};
  const message=`${label||(scope==='all'?'작업 전체':'지정한 파일')} ${paths.length}곡 저장?\n${planSummary(rows)}\n빈칸만: ${payload.only_empty?'예':'아니오'} / 파일명 변경: ${payload.rename?'예':'아니오'}`;
  saving=true;stopMediaPrefetch();updateSavePreview();
  try{
    if(!await confirmAction('저장 전 확인',message,'저장 실행','취소'))return;
    if(currentJobId!==jobId)throw new Error('확인 중 작업이 변경되었습니다. 저장 대상을 다시 확인하세요.');
    const saveRequest=api('/api/jobs/'+jobId+'/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    refreshSaveTasks();
    const res=await saveRequest;refreshSaveTasks();
    res.results.forEach(o=>{const r=currentResults.find(r=>r.path===(o.request_path||o.path));if(!r)return;
      if(o.lyrics_search)r._lyricsSearch={...o.lyrics_search,queryKey:lyricQueryKey(r)};
      if(o.changed&&r._lyricsSearch)r._lyricsSearch.lyrics_id=null;
      r.last_save=o;if(o.file_state)r.file_state=o.file_state;
      if(o.changed){manualCoverDraft(r,null,jobId);r._checked=false;r._dirty=false;}
      if(o.original){r.original=o.original;r.path=o.path;if(o.changed){r._draft=null;r._candidateFeedback=null;r._appliedFields=[];r._coverId=null;if(editingResult===r)editingResult=null;}}
    });
    renderFileList();if(selectedFileIdx>=0)selectFile(selectedFileIdx);reportSave(res);
  }catch(e){alert('저장 요청 실패: '+e.message);}finally{saving=false;updateSavePreview();scheduleMediaPrefetch();pumpCandidateMedia();}
}

async function saveCurrent(){if(!editingResult)return alert('파일을 선택하세요');return submitSave([editingResult],'current','현재 곡');}

function saveTarget(){sanitizeChecks();const rows=currentResults.filter(r=>r._checked&&fileState(r)==='auto');return {rows,scope:'all',label:`작업 전체 저장 (체크 ${rows.length}곡)`};}

async function saveAll(){const target=saveTarget();return submitSave(target.rows,'all','체크한 자동선택');}

async function saveSelected(){return submitSave(saveTarget().rows,'selected','체크한 자동선택');}

function plannedChanges(r){
  ensureDraft(r);const base=originalValues(r),active=r._selection!=='none';
  const emptyOnly=$('onlyEmpty').checked;
  const candidate=r.candidates?.find(c=>c.id===r._candidateId);
  const changes=tagFields.filter(f=>active&&r._fields.includes(f)&&(!emptyOnly||!base[f])&&String((r._selection==='auto'?candidateValues(candidate)[f]:r._draft[f])||'')!==String(base[f]));
  const cover=commonSaveCover&&(!emptyOnly||!r.original?.has_cover)&&(!!r._coverId||(active&&!!candidate&&hasCandidateCoverSource(r)));
  const final={...base};changes.forEach(f=>final[f]=String((r._selection==='auto'?candidateValues(candidate)[f]:r._draft[f])||''));
  const lyric=lyricPlan(r),lyrics=lyric.change;
  const timed=!!(lyricChoice(r)?.synced&&commonSaveLyrics&&!protectedAsset(r,'lyrics'));
  return {changes,cover,lyrics,lyrics_text:lyric.text,synced:timed&&$('saveSynced').checked&&!r.original?.has_synced,lrc:timed&&$('createLrc').checked,rename:$('renameFiles').checked,ids:active&&!!candidate&&$('includeIds').checked};
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
