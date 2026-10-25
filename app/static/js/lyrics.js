// Candidate and stored lyrics, lookup, protection and display.
// Definitions only; shared state and ordered startup live in app.js.

function candidateMediaKey(c,r){return JSON.stringify([currentJobId,r.path,r.original?.revision,c.id]);}

function requestCandidateLyrics(c,r,force=false,priority=false){
  const key=candidateMediaKey(c,r),jobId=currentJobId;let entry=candidateLyricsCache.get(key);
  if(entry&&entry.expires<Date.now()&&entry.status!=='loading'){candidateLyricsCache.delete(key);entry=null;}
  if(entry&&entry.status==='loading'&&force&&!entry.force)return entry.promise.then(value=>value.status==='unknown'||currentJobId!==jobId?value:requestCandidateLyrics(c,r,true,priority));
  if(entry&&(!force||entry.status==='loading')){
    if(priority)entry.priority=true;candidateLyricsCache.delete(key);candidateLyricsCache.set(key,entry);pumpCandidateMedia();return entry.promise;
  }
  entry={key,c,r,jobId:currentJobId,force,priority,status:'loading',expires:Infinity};entry.promise=new Promise(resolve=>entry.resolve=resolve);
  candidateLyricsCache.set(key,entry);candidateLyricsQueue.push(entry);pumpCandidateMedia();return entry.promise;
}

function pumpCandidateLyrics(){pumpCandidateMedia();}

function startCandidateLyrics(entry){
  candidateLyricsRunning++;
  const {c,r,jobId,force}=entry;
  api('/api/jobs/'+encodeURIComponent(jobId)+'/candidate-lyrics',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:r.path,candidate_id:c.id,expected_revision:r.original.revision,force})})
    .then(value=>{entry.status=value.status;entry.value=value;}).catch(()=>{entry.status='error';entry.value={status:'error',message:'가사 조회 오류'};}).finally(()=>{
      candidateLyricsRunning--;entry.expires=Date.now()+(entry.status==='found'?86400000:entry.status==='not_found'?1800000:60000);entry.resolve(entry.value);
      for(const [key,value] of candidateLyricsCache){if(candidateLyricsCache.size<=128)break;if(value.status!=='loading')candidateLyricsCache.delete(key);}
      pumpCandidateMedia();
    });
}

function applyLyricResult(r,value,queryKey,candidateId){
  if(value.status!=='found'||!value.lyrics?.trim()||r._lyricsEdited||protectedAsset(r,'lyrics'))return false;
  if(value.query_title!==undefined&&JSON.stringify([value.query_title,value.query_artist])!==queryKey)return false;
  r._lyricsSearch={...value,queryKey,candidateId};r._lyricsLookupStatus=null;
  if(editingResult===r)updateSavePreview();return true;
}

async function applySelectedLyrics(r,c,force=false){
  if(!r||!c||saving||protectedAsset(r,'lyrics'))return;
  const jobId=currentJobId,epoch=r._lyricsEpoch=(r._lyricsEpoch||0)+1,queryKey=lyricQueryKey(r),signature=JSON.stringify([effectiveLyricTags(r),r._candidateId]);
  const value=await requestCandidateLyrics(c,r,force,true);
  if(currentJobId!==jobId||editingResult!==r||r._candidateId!==c.id||r._lyricsEpoch!==epoch||signature!==JSON.stringify([effectiveLyricTags(r),r._candidateId])||r._lyricsEdited)return;
  if(!applyLyricResult(r,value,queryKey,c.id)){r._lyricsLookupStatus=value.status;updateSavePreview();}
}

function storedLyricsKey(r){return JSON.stringify([r.path,r.original?.revision]);}

function storedLyrics(r){return storedLyricsCache.get(storedLyricsKey(r));}

function loadStoredLyrics(r){
  if(!r)return;
  const key=storedLyricsKey(r);if(storedLyricsCache.has(key))return;
  const entry={status:'ready',lyrics:''};storedLyricsCache.set(key,entry);
  while(storedLyricsCache.size>64)storedLyricsCache.delete(storedLyricsCache.keys().next().value);
  if(!r.original?.has_lyrics&&!r.original?.lyrics)return;
  entry.status='loading';
  api('/api/lyrics/'+encodeURIComponent(r.path)+'?v='+encodeURIComponent(r.original.revision||'')).then(value=>{entry.status='ready';entry.lyrics=value.lyrics||'';}).catch(error=>{entry.status='error';entry.message='가사 읽기 실패: '+error.message;}).finally(()=>{if(editingResult&&storedLyricsKey(editingResult)===key)updateSavePreview();});
}

function effectiveLyricTags(r){
  ensureDraft(r);const final=originalValues(r),candidate=r.candidates?.find(c=>c.id===r._candidateId),active=r._selection!=='none';
  tagFields.forEach(f=>{if(active&&r._fields.includes(f)&&(!$('onlyEmpty').checked||!final[f]))final[f]=String((r._selection==='auto'?candidateValues(candidate)[f]:r._draft[f])||'');});
  return final;
}

function lyricQueryKey(r){const final=effectiveLyricTags(r);return JSON.stringify([final.title,final.artist]);}

function lyricChoice(r){const state=r._lyricsSearch;return commonSaveLyrics&&!protectedAsset(r,'lyrics')&&state&&state.status!=='searching'&&state.lyrics_id&&state.queryKey===lyricQueryKey(r)&&(!state.candidateId||state.candidateId===r._candidateId)?state:null;}

function lyricPlan(r){
  const choice=lyricChoice(r),existing=r.original?.has_lyrics&&!r.original?.lyrics_marker;
  if(!commonSaveLyrics||protectedAsset(r,'lyrics')||($('onlyEmpty').checked&&existing))return {change:false,text:null};
  const current=storedLyrics(r);
  if(choice){const valid=choice.status==='found'&&!!choice.lyrics?.trim();return {change:valid&&(!current||current.status!=='ready'||choice.lyrics.trim()!==current.lyrics.trim()),text:valid?choice.lyrics:null};}
  return {change:false,text:null};
}

function paintLyrics(id,text,empty=false,preview=false){
  const box=$(id);if(id==='changeLyrics'){box.value=empty?'':text;box.placeholder=empty?text:'';box.textContent=text;}else if(box.textContent!==text){box.textContent=text;box.scrollTop=0;}
  box.className='lyrics-body'+(empty?' lyrics-empty':'')+(preview?' lyrics-preview':'');
}

function renderLyricsPanels(r,active=false,plan=null){
  $('changeLyrics').title='';
  $('changeLyrics').readOnly=!r||protectedAsset(r,'lyrics')||!r._lyricsSearch?.lyrics_id;
  if(!r){paintLyrics('currentLyrics','가사 없음',true);paintLyrics('changeLyrics','검색 안 함',true);$('btnSearchLyrics').disabled=true;return;}
  loadStoredLyrics(r);const current=storedLyrics(r),state=r._lyricsSearch;
  const preview=active&&plan?.lyrics_text&&plan.lyrics&&(current?.status==='ready'||!r.original?.has_lyrics);
  if(preview)paintLyrics('currentLyrics',plan.lyrics_text,false,true);
  else if(current?.status==='loading')paintLyrics('currentLyrics','불러오는 중...',true);
  else if(current?.status==='error')paintLyrics('currentLyrics',current.message,true);
  else paintLyrics('currentLyrics',current?.lyrics||'가사 없음',!current?.lyrics);
  if(!state)paintLyrics('changeLyrics','검색 안 함',true);
  else if(state.status==='searching')paintLyrics('changeLyrics','검색 중...',true);
  else if(state.queryKey!==lyricQueryKey(r)||(!r._lyricsEdited&&state.candidateId&&state.candidateId!==r._candidateId)){
    paintLyrics('changeLyrics',state.lyrics||'태그가 변경되었습니다. 다시 검색해 주세요.',!state.lyrics);
    $('changeLyrics').title='현재 선택한 곡과 검색 조건이 달라 저장에서 제외됩니다. 가사를 다시 검색해 주세요.';
  }
  else if(state.status==='found'&&(state.lyrics||r._lyricsEdited))paintLyrics('changeLyrics',state.lyrics);
  else if(state.status==='not_found')paintLyrics('changeLyrics','검색 결과 없음',true);
  else paintLyrics('changeLyrics',state.message||'가사 검색 오류가 발생했습니다. 다시 시도해 주세요.',true);
  if(r._lyricsLookupStatus&&!state)paintLyrics('changeLyrics',r._lyricsLookupStatus==='not_found'?'검색 결과 없음':'가사 조회 오류',true);
  $('btnSearchLyrics').disabled=!!r._lyricsRequest?.active||saving;
}

async function searchLyricsForCurrent(){
  if(!editingResult||saving)return;captureCurrent();const r=editingResult,jobId=currentJobId;
  if(r._lyricsRequest?.active)return;
  const tags=effectiveLyricTags(r),queryKey=lyricQueryKey(r),candidateId=r._candidateId,epoch=r._lyricsEpoch=(r._lyricsEpoch||0)+1;
  const previous=r._lyricsSearch,request={active:true},placeholder={status:'searching',queryKey};r._lyricsRequest=request;
  if(!previous)r._lyricsSearch=placeholder;updateSavePreview();
  try{
    const value=await api('/api/jobs/'+encodeURIComponent(jobId)+'/lyrics-search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:r.path,expected_revision:r._draftRevision,title:tags.title,artist:tags.artist,force:true,candidate_id:candidateId||null})});
    if(currentJobId===jobId&&editingResult===r&&r._lyricsEpoch===epoch&&queryKey===lyricQueryKey(r)&&candidateId===r._candidateId&&!r._lyricsEdited){
      if(!applyLyricResult(r,value,queryKey,candidateId))r._lyricsSearch=previous||{...value,queryKey,candidateId};
    }
  }catch(error){if(!previous&&r._lyricsEpoch===epoch)r._lyricsSearch={status:'error',queryKey,message:'가사 검색 오류: '+error.message};}
  finally{
    if(placeholder.status==='searching')Object.assign(placeholder,{status:'error',message:'다시 검색해 주세요.'});
    if(r._lyricsSearch===placeholder)r._lyricsSearch=previous||null;
    request.active=false;if(r._lyricsRequest===request)r._lyricsRequest=null;
    if(currentJobId===jobId&&editingResult===r)updateSavePreview();
  }
}

function showLyricsStatus(r){renderLyricsPanels(r);}
