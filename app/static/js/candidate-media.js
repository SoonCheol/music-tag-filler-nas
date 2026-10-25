// Candidate rendering, cover images, audio and the shared media queue.
// Definitions only; shared state and ordered startup live in app.js.

function stopRenamedAudio(path){
  if(playingPath!==path)return;
  ++audioRequest;previewAudio.pause();previewAudio.removeAttribute('src');previewAudio.load();
  playingPath=null;audioPlaying=false;audioUnavailable.delete(path);updateAudioButtons();
}

function audioMime(path){return {mp3:'audio/mpeg',flac:'audio/flac',m4a:'audio/mp4',ogg:'audio/ogg'}[(path.split('.').pop()||'').toLowerCase()]||'';}

function canPreviewAudio(path){const mime=audioMime(path);return !!mime&&typeof previewAudio.canPlayType==='function'&&!!previewAudio.canPlayType(mime)&&!audioUnavailable.has(path);}

function audioButton(path,index){
  const playing=playingPath===path&&audioPlaying,label=playing?'일시정지':'재생';
  return `<button type="button" class="audio-preview-button${playing?' playing':''}" data-audio-path="${esc(path)}" ${canPreviewAudio(path)?'':'disabled'} title="${canPreviewAudio(path)?label:'브라우저에서 재생할 수 없는 파일'}" aria-label="${label}: ${esc(path)}" onclick="event.stopPropagation();toggleAudio(${index})">${playing?'⏸':'▶'}</button>`;
}

function updateAudioButtons(){
  const header=$('headerAudio'),label=audioPlaying?'일시정지':'이어서 재생';
  header.textContent=audioPlaying?'⏸':'▶';header.className='audio-preview-button'+(audioPlaying?' playing':'');
  header.disabled=!playingPath||!canPreviewAudio(playingPath);
  header.title=header.disabled?'먼저 파일의 재생 버튼을 눌러 주세요':label+': '+playingPath;
  header.setAttribute('aria-label',header.disabled?'현재 음악 재생':label+': '+playingPath);
  document.querySelectorAll('[data-audio-path]').forEach(button=>{
    const path=button.getAttribute('data-audio-path'),playing=path===playingPath&&audioPlaying,label=playing?'일시정지':'재생';
    button.textContent=playing?'⏸':'▶';button.className='audio-preview-button'+(playing?' playing':'');
    button.disabled=!canPreviewAudio(path);button.title=button.disabled?'브라우저에서 재생할 수 없는 파일':label;button.setAttribute('aria-label',label+': '+path);
  });
}

async function toggleHeaderAudio(){
  if(!playingPath||!canPreviewAudio(playingPath))return;
  if(!previewAudio.paused){++audioRequest;previewAudio.pause();return;}
  const path=playingPath,token=++audioRequest;
  try{await previewAudio.play();if(token===audioRequest)updateAudioButtons();}
  catch(error){if(token!==audioRequest||error.name==='AbortError')return;if(error.name==='NotSupportedError')audioUnavailable.add(path);audioPlaying=false;previewAudio.pause();updateAudioButtons();}
}

async function toggleAudio(index){
  const row=filteredResults[index];if(!row||!canPreviewAudio(row.path))return;
  const path=row.path;
  if(playingPath===path&&!previewAudio.paused){previewAudio.pause();audioPlaying=false;updateAudioButtons();return;}
  const token=++audioRequest;
  if(playingPath!==path||previewAudio.error){previewAudio.pause();audioPlaying=false;playingPath=path;previewAudio.src='/api/audio/'+encodeURIComponent(path);previewAudio.load();}
  try{await previewAudio.play();if(token===audioRequest)updateAudioButtons();}
  catch(error){if(token!==audioRequest||error.name==='AbortError')return;if(error.name==='NotSupportedError')audioUnavailable.add(path);audioPlaying=false;previewAudio.pause();updateAudioButtons();}
}

function fileMediaIcons(r){
  const original=r.original||{},lyrics=!!original.has_lyrics;
  const cover=original.has_cover?`<img data-file-thumbnail data-src="/api/thumbnail/${encodeURIComponent(r.path)}?v=${encodeURIComponent(original.revision||'')}" alt="저장된 커버" decoding="async" onerror="this.hidden=true">`:'';
  return `<span class="file-cover" title="${original.has_cover?'저장된 커버':'커버 없음'}" role="img" aria-label="${original.has_cover?'저장된 커버':'커버 없음'}">♪${cover}</span><span class="file-lyrics${lyrics?' has-lyrics':''}" title="저장된 가사 ${lyrics?'있음':'없음'}" aria-label="저장된 가사 ${lyrics?'있음':'없음'}">L</span>`;
}

function requestCandidateCover(c,r,retry=false,priority=false){
  const key=candidateCoverUrl(c,r);if(!key)return Promise.resolve(null);
  let entry=candidateCoverCache.get(key);
  if(entry&&entry.expires<Date.now()&&entry.status!=='pending'){candidateCoverCache.delete(key);entry=null;}
  if(entry&&(!retry||entry.status==='pending')){
    if(priority){entry.priority=true;const index=candidateCoverQueue.indexOf(entry);if(index>0){candidateCoverQueue.splice(index,1);candidateCoverQueue.unshift(entry);}}
    candidateCoverCache.delete(key);candidateCoverCache.set(key,entry);return entry.promise;
  }
  entry={key,priority,path:r.path,jobId:currentJobId,status:'pending',expires:Infinity,previous:entry?.url||null,url:key+(retry?'&force=true&retry='+ ++candidateCoverAttempt:'')};
  entry.promise=new Promise(resolve=>entry.resolve=resolve);candidateCoverCache.set(key,entry);
  if(priority)candidateCoverQueue.unshift(entry);else candidateCoverQueue.push(entry);
  pumpCandidateCovers();return entry.promise;
}

function pumpCandidateCovers(){pumpCandidateMedia();}

function pumpCandidateMedia(){
  // One shared budget for images AND lyrics. User requests jump queued prefetch.
  while(candidateCoverRunning+candidateLyricsRunning<2){
    let ci=candidateCoverQueue.findIndex(e=>e.priority),li=candidateLyricsQueue.findIndex(e=>e.priority);
    if(ci>=0){startCandidateCover(candidateCoverQueue.splice(ci,1)[0]);continue;}
    if(li>=0){startCandidateLyrics(candidateLyricsQueue.splice(li,1)[0]);continue;}
    if(saving||searching||mediaJobStatus!=='done')break;
    if(candidateCoverQueue.length){startCandidateCover(candidateCoverQueue.shift());continue;}
    if(candidateLyricsQueue.length){startCandidateLyrics(candidateLyricsQueue.shift());continue;}
    break;
  }
}

function startCandidateCover(entry){
  candidateCoverRunning++;
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),45000);
  fetch(entry.url,{signal:controller.signal,cache:'no-store'}).then(async response=>{
    if(!response.ok){const detail=await response.json().catch(()=>({}));entry.status=response.status===404&&(detail.detail?.state==='none'||!(detail.detail?.errors?.length))?'none':'error';return null;}
    const blob=await response.blob();if(!blob.type.startsWith('image/'))throw new Error('유효하지 않은 이미지');
    entry.blob=blob;return URL.createObjectURL(blob);
  }).then(url=>finish(url)).catch(()=>{entry.status='error';finish(null);});
  function finish(url){
    clearTimeout(timeout);entry.status=url?'ready':entry.status==='none'?'none':'error';
    entry.expires=Date.now()+(url?600000:30000);entry.url=url||entry.previous||null;
    candidateCoverRunning--;entry.resolve(entry.url);
    for(const [key,value] of candidateCoverCache){if(candidateCoverCache.size<=64)break;if(value.status!=='pending'){candidateCoverCache.delete(key);if(value.url?.startsWith('blob:'))URL.revokeObjectURL(value.url);}}
    pumpCandidateMedia();
  }
}

function stopMediaPrefetch(){
  clearTimeout(mediaPrefetchTimer);mediaPrefetchTimer=null;
  candidateListGeneration++;
  for(const entry of candidateCoverQueue.splice(0)){candidateCoverCache.delete(entry.key);entry.resolve(null);}
  for(const entry of candidateLyricsQueue.splice(0)){candidateLyricsCache.delete(entry.key);entry.resolve({status:'unknown'});}
  currentResults.forEach(r=>r._lyricsEpoch=(r._lyricsEpoch||0)+1);
}

function scheduleMediaPrefetch(){
  if(mediaJobStatus!=='done'||mediaPrefetchTimer||saving||searching)return;
  mediaPrefetchTimer=setTimeout(()=>{mediaPrefetchTimer=null;prefetchVisibleMedia();},80);
}

function prefetchVisibleMedia(){
  if(mediaJobStatus!=='done'||saving||searching)return;
  const box=$('fileListScroller').getBoundingClientRect?.();if(!box)return;
  const visible=filteredResults.filter(r=>{const rect=fileRowNodes.get(r.path)?.getBoundingClientRect?.();return rect&&rect.bottom>box.top&&rect.top<box.bottom;}).slice(0,16);
  const targets=new Set(visible.map(r=>r.path));
  // Drop background work that scrolled out before it started.
  for(let i=candidateCoverQueue.length-1;i>=0;i--){const e=candidateCoverQueue[i];if(!e.priority&&!targets.has(e.path)){candidateCoverQueue.splice(i,1);candidateCoverCache.delete(e.key);e.resolve(null);}}
  for(let i=candidateLyricsQueue.length-1;i>=0;i--){const e=candidateLyricsQueue[i];if(!e.priority&&!targets.has(e.r.path)&&e.r!==editingResult){candidateLyricsQueue.splice(i,1);candidateLyricsCache.delete(e.key);e.resolve({status:'unknown'});}}
  visible.forEach(r=>{ensureDraft(r);const c=r.candidates?.find(c=>c.id===r._candidateId);if(!c)return;
    if(!protectedAsset(r,'cover'))requestCandidateCover(c,r);
    if(!protectedAsset(r,'lyrics'))requestCandidateLyrics(c,r);
  });
  $('candidateScroller')._visibleMedia?.();
}

function paintCandidateCover(box,c,r,retry=false){
  const key=candidateCoverUrl(c,r);if(box._candidateCoverKey===key&&!retry)return;
  box._candidateCoverKey=key;const token=box._candidateCoverToken=(box._candidateCoverToken||0)+1;
  box.innerHTML='<span role="status">이미지 조회 중…</span>';
  requestCandidateCover(c,r,retry,true).then(url=>{
    if(box._candidateCoverToken!==token||box._candidateCoverKey!==key)return;
    const state=candidateCoverCache.get(key)?.status;
    box.innerHTML=url?`<img src="${url}" alt="후보 커버">`+(state==='error'?'<span role="status">재조회 오류 · 이전 이미지 유지</span>':''):
      state==='none'?'<span role="status">이미지 없음</span>':'<span role="status">이미지 조회 오류 · 후보 이미지 클릭으로 재시도</span>';
  });
}

function invalidateCandidateCover(box){box._candidateCoverKey=null;box._candidateCoverToken=(box._candidateCoverToken||0)+1;}

function hideHoverCover(){hoverCoverToken++;hoverCoverTarget=null;hoverCoverFailed=false;$('hoverPrev').style.display='none';}

function showHoverCover(c,r,retry=false){
  const token=++hoverCoverToken,url=candidateCoverUrl(c,r);hoverCoverTarget={c,r};hoverCoverFailed=false;
  $('hoverPrev').style.display='block';$('hoverCoverImage').replaceChildren();
  $('hoverCoverStatus').textContent=url?'커버 불러오는 중…':'일치하는 커버가 없습니다.';
  if(!url)return;
  requestCandidateCover(c,r,retry,true).then(src=>{
    if(token!==hoverCoverToken)return;
    if(src){const img=document.createElement('img');img.alt='후보 커버';img.src=src;$('hoverCoverStatus').textContent=candidateCoverCache.get(url)?.status==='error'?'재조회 오류 · 이전 이미지 유지':'';$('hoverCoverImage').replaceChildren(img);}
    else{hoverCoverFailed=true;const state=candidateCoverCache.get(url)?.status;$('hoverCoverStatus').textContent=state==='none'?'일치하는 커버가 없습니다.':'커버 조회 오류 · 클릭하여 다시 시도하세요.';}
  });
}

function retryHoverCover(){if(hoverCoverTarget)showHoverCover(hoverCoverTarget.c,hoverCoverTarget.r,true);}

async function importCandidateCover(c,r){
  if(saving||searching||protectedAsset(r,'cover'))return alert('빈 태그만 채우기: 기존 앨범 이미지를 보호합니다.');
  const jobId=currentJobId;captureCurrent();
  try{
    const url=await requestCandidateCover(c,r,false,true);if(!url)throw new Error('가져올 이미지가 없습니다');
    const response=await fetch(url);if(!response.ok)throw new Error('이미지를 읽을 수 없습니다');
    const blob=await response.blob(),value=await api('/api/jobs/'+encodeURIComponent(jobId)+'/cover-upload',{method:'POST',headers:{'Content-Type':blob.type},body:blob});
    r._coverId=value.cover_id;manualCoverDraft(r,r._coverId,jobId);r._dirty=true;commonSaveCover=true;
    if(r._selection==='none')r._selection='edit';
    if(editingResult===r&&currentJobId===jobId){syncEditProtection(r);renderChangeCover(r);updateSavePreview();}
  }catch(error){alert('이미지 가져오기 실패: '+error.message);}
}

function renderCandidates(r){
  hideHoverCover();const generation=++candidateListGeneration,thumbs=[];
  // Remove only queued work from the previous viewport; active requests keep their own keys.
  for(let index=candidateCoverQueue.length-1;index>=0;index--){const entry=candidateCoverQueue[index];if(!entry.priority){candidateCoverQueue.splice(index,1);candidateCoverCache.delete(entry.key);entry.resolve(null);}}
  for(const item of candidateLyricsQueue.splice(0)){candidateLyricsCache.delete(candidateMediaKey(item.c,item.r));item.resolve({status:'unknown'});}
  const body=$('candBody');body.innerHTML='';
  if(!r.candidates?.length){body.innerHTML='<tr><td colspan="8" style="text-align:center;padding:12px;color:#999">후보 없음</td></tr>';return;}
  r.candidates.forEach((c,i)=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td class="candidate-score">${esc(c.score)}</td><td class="candidate-icon-cell"><button type="button" class="candidate-thumb" id="candidateThumb${generation}-${i}" title="커버 미확인 · 클릭: 재조회 / 더블클릭: 이미지만 가져오기" aria-label="커버 미리보기">♪</button></td><td class="candidate-icon-cell"><button type="button" class="file-lyrics candidate-lyrics" id="candidateLyrics${generation}-${i}" title="가사 미확인 · 클릭하여 재조회">?</button></td><td title="${esc(c.title)}"><div class="candidate-title"><span class="candidate-name">${esc(c.title)}</span></div></td><td title="${esc(c.artist)}">${esc(c.artist)}</td><td title="${esc(c.album)}">${esc(c.album)}</td><td>${esc(c.year)}</td><td>${esc(c.source)}</td>`;
    tr.onclick=()=>{document.querySelectorAll('#candBody tr').forEach(el=>el.classList.remove('selected'));tr.classList.add('selected');applyCandidate(r,c);};
    body.appendChild(tr);const thumb=$(`candidateThumb${generation}-${i}`),lyric=$(`candidateLyrics${generation}-${i}`);thumbs.push({c,thumb,lyric,tr});
    let clickTimer=null;
    thumb.onmouseenter=()=>showHoverCover(c,r);
    thumb.onmousemove=e=>{const hp=$('hoverPrev');hp.style.left=Math.max(10,Math.min(e.clientX+14,window.innerWidth-272))+'px';hp.style.top=Math.max(10,Math.min(e.clientY+14,window.innerHeight-252))+'px';};
    thumb.onmouseleave=hideHoverCover;
    thumb.onclick=event=>{event.stopPropagation();clearTimeout(clickTimer);if(event.detail>1)return;clickTimer=setTimeout(()=>loadThumb(thumb,c,true),550);};
    thumb.ondblclick=event=>{event.stopPropagation();clearTimeout(clickTimer);importCandidateCover(c,r);};
    lyric.onclick=event=>{event.stopPropagation();loadLyrics(lyric,c,true);if(r._candidateId===c.id)applySelectedLyrics(r,c,true);};
  });
  function loadThumb(thumb,c,force=false){
    thumb.dataset.state='loading';thumb.title='이미지 조회 중';
    requestCandidateCover(c,r,force).then(url=>{
      if(generation!==candidateListGeneration)return;
      const state=candidateCoverCache.get(candidateCoverUrl(c,r))?.status||'unknown';thumb.dataset.state=state;
      thumb.innerHTML=url?`<img src="${url}" alt="">`:'♪';
      thumb.title=({ready:'앨범 이미지',none:'이미지 없음',error:'이미지 조회 오류',unknown:'이미지 미확인'})[state]+' · 클릭: 재조회 / 더블클릭: 이미지만 가져오기';
      if(editingResult===r&&r._candidateId===c.id&&!r._coverId)renderChangeCover(r);
    });
  }
  function loadLyrics(button,c,force=false){
    button.dataset.state='loading';button.textContent='…';button.title='가사 조회 중';
    requestCandidateLyrics(c,r,force,force).then(value=>{
      const state=value.status==='not_found'?'none':value.status;
      if(generation!==candidateListGeneration)return;
      button.dataset.state=state;button.textContent=state==='error'?'!':'L';button.className='file-lyrics candidate-lyrics'+(state==='found'?' has-lyrics':'');
      button.title=({found:'가사 있음',none:'가사 없음',error:'가사 조회 오류',unknown:'가사 미확인'})[state]+' · 클릭하여 재조회';
    });
  }
  function visible(){
    if(!r._candidateMediaEntered)return;
    const rect=$('candidateScroller').getBoundingClientRect();
    const visibleKeys=new Set(thumbs.filter(({tr})=>{const row=tr.getBoundingClientRect();return row.bottom>rect.top&&row.top<rect.bottom;}).map(({c})=>candidateCoverUrl(c,r)));
    for(let i=candidateCoverQueue.length-1;i>=0;i--){const entry=candidateCoverQueue[i];if(!entry.priority&&!visibleKeys.has(entry.key)){candidateCoverQueue.splice(i,1);candidateCoverCache.delete(entry.key);entry.resolve(null);}}
    for(let i=candidateLyricsQueue.length-1;i>=0;i--){const item=candidateLyricsQueue[i];if(!visibleKeys.has(candidateCoverUrl(item.c,item.r))){candidateLyricsQueue.splice(i,1);candidateLyricsCache.delete(candidateMediaKey(item.c,item.r));item.resolve({status:'unknown'});}}
    thumbs.forEach(({c,thumb,lyric,tr})=>{const row=tr.getBoundingClientRect();if(row.bottom<=rect.top||row.top>=rect.bottom)return;
      if(!thumb.dataset.state||thumb.dataset.state==='unknown')loadThumb(thumb,c);if(!lyric.dataset.state||lyric.dataset.state==='unknown')loadLyrics(lyric,c);
    });
  }
  $('candidateScroller').onmouseenter=()=>{r._candidateMediaEntered=true;visible();};
  $('candidateScroller').onscroll=visible;$('candidateScroller')._visibleMedia=visible;
  if(mediaJobStatus==='done'){r._candidateMediaEntered=true;visible();}
}

function renderChangeCover(r){
  const box=$('changeCover');invalidateCandidateCover(box);
  const original=r?.original?.has_cover?`<img src="/api/cover/${encodeURIComponent(r.path)}?v=${r.original.revision}" onerror="this.parentElement.textContent='no image'">`:'<span>no image</span>';
  if(!r||!$('saveCover').checked||($('onlyEmpty').checked&&r.original?.has_cover)){box.innerHTML=original;return;}
  if(r._coverId){box.innerHTML=`<img src="/api/jobs/${encodeURIComponent(currentJobId)}/uploaded-cover/${encodeURIComponent(r._coverId)}" onerror="this.parentElement.textContent='수동 선택 이미지 만료 또는 조회 오류 · 이미지를 다시 선택하세요'">`;return;}
  const candidate=r.candidates?.find(c=>c.id===r._candidateId);
  if(candidate&&candidateCoverUrl(candidate,r))paintCandidateCover(box,candidate,r);else box.innerHTML=candidate?'<span role="status">이미지 없음</span>':original;
}

function hasCandidateCoverSource(r){
  const candidate=r.candidates?.find(c=>c.id===r._candidateId);
  const url=candidate?candidateCoverUrl(candidate,r):'';
  return !!url&&!['failed','none','error'].includes(candidateCoverCache.get(url)?.status);
}

function candidateCoverUrl(c,r){return c.id&&(c.cover_url||c.album)?`/api/jobs/${encodeURIComponent(currentJobId)}/cover/${encodeURIComponent(c.id)}?path=${encodeURIComponent(r.path)}${r.country?'&country='+encodeURIComponent(r.country):''}`:'';}

async function uploadCover(file){
  if(protectedAsset(editingResult,'cover'))return alert('빈 태그만 채우기: 기존 앨범 이미지를 보호합니다.');
  if(!editingResult)return alert('파일을 선택하세요');if(saving||searching)return;
  if(!file||file.size>20*1024*1024)return alert('20MB 이하 이미지를 선택하세요');
  captureCurrent();const r=editingResult,jobId=currentJobId;searching=true;
  try{const value=await api('/api/jobs/'+jobId+'/cover-upload',{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:file});r._coverId=value.cover_id;manualCoverDraft(r,r._coverId,jobId);r._dirty=true;if(r._selection==='none'||r._selection==='auto')r._selection='edit';if(editingResult===r){editingResult=null;selectFile(filteredResults.indexOf(r));}$('statusLine').textContent='커버 준비 완료 — 저장 전까지 음악 파일은 변경되지 않습니다';}catch(e){alert('커버 선택 실패: '+e.message);}finally{searching=false;updateSavePreview();}
}

async function applyCoverToAll(){
  if(!editingResult||saving||searching)return;captureCurrent();const r=editingResult,jobId=currentJobId;
  if(!await confirmAction('커버 준비','현재 작업 전체 '+currentResults.length+'곡에 같은 커버를 준비할까요? 실제 기록은 저장할 때 수행합니다.','준비 실행','취소'))return;
  try{if(!r._coverId){const c=r.candidates?.find(c=>c.id===r._candidateId);const url=c?candidateCoverUrl(c,r):r.original?.has_cover?'/api/cover/'+encodeURIComponent(r.path):'';if(!url)throw new Error('선택한 커버가 없습니다');searching=true;const response=await fetch(url);if(!response.ok)throw new Error('커버 읽기 실패');const image=await response.blob();const value=await api('/api/jobs/'+jobId+'/cover-upload',{method:'POST',headers:{'Content-Type':image.type},body:image});r._coverId=value.cover_id;}
    currentResults.forEach(row=>{ensureDraft(row);row._coverId=r._coverId;manualCoverDraft(row,row._coverId,jobId);row._dirty=true;if(row._selection==='none'||row._selection==='auto')row._selection='edit';});editingResult=null;selectFile(filteredResults.indexOf(r));alert('전체 커버 준비 완료. 빈칸만 옵션과 저장 범위는 그대로 적용됩니다.');
  }catch(e){alert(e.message);}finally{searching=false;updateSavePreview();}
}
