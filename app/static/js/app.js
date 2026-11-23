// Shared global state, common utilities, event bindings and startup.
// Keep executable statements in their original order; load feature definitions first.

let currentJobId=null,allJobs=[],currentResults=[],filteredResults=[],selectedFileIdx=-1;
let lastSaveTasks=[],jobsPolling=false,jobPollTimer=null,jobsRefreshRequested=false,lastDetailRevision=null;
const selectedBackgroundJobs=new Set();
const scanBrowserTimes=new Map();

let renameEditor=null,renameBusy=false,pathChangeCursor=0;
let editingResult=null,displayedJobId=null,saving=false,searching=false,lastJobSignature='';
const tagFields=['title','artist','album','albumartist','track','year','genre'];
let commonTagFields=[...tagFields],commonSaveCover=true,commonSaveLyrics=true;

let previewPath=null,previewRevision=null;
const draftJobs=new Map();
let actionResolver=null;

$('actionDialog').addEventListener('cancel',e=>{e.preventDefault();resolveAction(false);});
$('actionDialog').addEventListener('close',()=>{if(actionResolver)resolveAction(false);});

function $(id){return document.getElementById(id)}
function api(p,o={}){return fetch(p,o).then(async r=>{const t=await r.text();let j;try{j=JSON.parse(t)}catch{j={raw:t}};if(!r.ok){const e=new Error(j.detail?.message||j.detail||t);e.status=r.status;e.detail=j.detail;throw e;}return j;});}
function esc(s){return (s??'').toString().replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
let musicFolders=[],pendingFolder=$('subPath').value;

let restoredView=null,viewPinned=false;

restoredView=readView();
if(restoredView){viewPinned=true;$('subPath').value=restoredView.folder;pendingFolder=restoredView.folder;currentJobId=typeof restoredView.jobId==='string'?restoredView.jobId:null;$('fileFilter').value=typeof restoredView.filter==='string'?restoredView.filter:'';}
folderLabel();

const expandedFolders=new Set();
try{JSON.parse(localStorage.getItem('musicFolderExpansion')||'[]').filter(p=>typeof p==='string').forEach(p=>expandedFolders.add(p));}catch(e){}

$('folderToggle').onclick=()=>{
  const opening=$('folderMenu').hidden; $('folderMenu').hidden=!opening;
  $('folderToggle').setAttribute('aria-expanded',String(opening));
  if(opening){ $('folderSearch').value=''; renderFolders(); $('folderSearch').focus(); }
};
$('folderSearch').addEventListener('input',renderFolders);
$('folderMenu').addEventListener('click',e=>e.stopPropagation());
$('folderPicker').addEventListener('keydown',e=>{ if(e.key==='Escape'){ closeFolderMenu(); $('folderToggle').focus(); } });
document.addEventListener('click',e=>{ if(!$('folderPicker').contains(e.target)) closeFolderMenu(); });

let operationExpanded=false,operationItems=[];

let fileSortColumn=null,fileSortDirection=1;
const fileNameCompare=(a,b)=>a.path.split('/').pop().localeCompare(b.path.split('/').pop(),'ko',{numeric:true,sensitivity:'base'})||a.path.localeCompare(b.path,'ko',{numeric:true});

const previewAudio=$('previewAudio');
let playingPath=null,audioPlaying=false,audioRequest=0;
const audioUnavailable=new Set();

previewAudio.addEventListener('playing',()=>{audioPlaying=true;updateAudioButtons();});
previewAudio.addEventListener('pause',()=>{audioPlaying=false;updateAudioButtons();});
previewAudio.addEventListener('ended',()=>{audioPlaying=false;playingPath=null;updateAudioButtons();});
previewAudio.addEventListener('error',()=>{
  if(previewAudio.currentSrc&&previewAudio.currentSrc!==previewAudio.src)return;
  if(playingPath&&[3,4].includes(previewAudio.error?.code))audioUnavailable.add(playingPath);
  audioPlaying=false;previewAudio.pause();updateAudioButtons();
});
let fileRowNodes=new Map();
const fileThumbnailObserver=typeof IntersectionObserver==='function'?new IntersectionObserver(entries=>{
  entries.forEach(entry=>{if(entry.isIntersecting){const image=entry.target;image.src=image.dataset.src;image.removeAttribute('data-file-thumbnail');fileThumbnailObserver.unobserve(image);}});
},{root:$('fileListScroller'),rootMargin:'0px'}):null;

const candidateCoverCache=new Map(),candidateCoverQueue=[];
let candidateCoverRunning=0,candidateCoverAttempt=0,candidateListGeneration=0;

let mediaJobStatus=null,mediaPrefetchTimer=null;

$('fileListScroller').addEventListener('scroll',scheduleMediaPrefetch);
$('fileListScroller').addEventListener('mousedown',event=>{
  if(!event.target.closest('input,textarea,select,button,a,[contenteditable]'))$('fileListScroller').focus({preventScroll:true});
});
$('fileListScroller').addEventListener('keydown',navigateFileList);

let hoverCoverToken=0,hoverCoverTarget=null,hoverCoverFailed=false;

$('hoverPrev').addEventListener('mouseleave',hideHoverCover);
const candidateLyricsCache=new Map(),candidateLyricsQueue=[];
let candidateLyricsRunning=0;

$('saveCover').addEventListener('change',()=>{if(!$('saveCover').disabled)commonSaveCover=$('saveCover').checked;renderChangeCover(editingResult);updateSavePreview();});
$('saveLyrics').addEventListener('change',()=>{if(!$('saveLyrics').disabled)commonSaveLyrics=$('saveLyrics').checked;updateSavePreview();});

const storedLyricsCache=new Map();

$('changeLyrics').addEventListener('input',()=>{
  const r=editingResult;if(!r)return;
  r._lyricsEdited=true;r._dirty=true;r._lyricsEpoch=(r._lyricsEpoch||0)+1;
  r._lyricsDraft=$('changeLyrics').value;updateSavePreview();
});

const fieldLabels={title:'제목',artist:'가수',album:'앨범',albumartist:'앨범 가수',track:'트랙',year:'년도',genre:'장르'};

tagFields.forEach(f=>$('chg_'+f).addEventListener('input',()=>{if(editingResult){captureCurrent();editingResult._dirty=true;editingResult._manualFields=[...new Set([...(editingResult._manualFields||[]),f])];editingResult._selection='edit';editingResult._candidateFeedback=null;editingResult._appliedFields=[];updateSavePreview();}}));
document.querySelectorAll('.chg-check').forEach(c=>c.addEventListener('change',()=>{if(c.disabled)return;commonTagFields=tagFields.filter(f=>f===c.dataset.field?c.checked:commonTagFields.includes(f));captureCurrent();updateSavePreview();}));

$('searchQ').title='국가 지정: @JP 가수 - 제목 (@KR/@US 등). 음향 검색: @sound 또는 @JP @sound';
$('searchQ').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();manualSearch();}});
let confirmedFilter=$('fileFilter').value;
$('fileFilter').addEventListener('input',async()=>{const q=$('fileFilter').value;if(editingResult&&!editingResult.path.toLowerCase().includes(q.toLowerCase())&&!await allowDraftMove()){$('fileFilter').value=confirmedFilter;return;}confirmedFilter=q;currentResults.forEach(r=>delete r._renameVisible);applyFilter();persistView();});

const modalOptionIds=['onlyEmpty','fillLyrics','saveSynced','createLrc','renameFiles','includeIds','searchCountry','artistPreference','coverMax','scanPaths'];
const modalCheckboxIds=['onlyEmpty','fillLyrics','saveSynced','createLrc','renameFiles','includeIds'];
let optionsSnapshot=null;

$('saveOptionsDialog').addEventListener('cancel',event=>{event.preventDefault();cancelSaveOptions();});

['onlyEmpty','fillLyrics','saveSynced','createLrc','renameFiles','includeIds'].forEach(id=>$(id).addEventListener('change',()=>{captureCurrent();if(id==='onlyEmpty'){syncEditProtection(editingResult);renderChangeCover(editingResult);}updateSavePreview();}));
$('coverFile').addEventListener('change',e=>{uploadCover(e.target.files[0]);e.target.value='';});
$('changeCover').addEventListener('dragover',e=>e.preventDefault());
$('changeCover').addEventListener('drop',e=>{e.preventDefault();uploadCover(e.dataTransfer.files[0]);});
const buttonHelp={
  btnApplyCandidate:'아래 편집 내용을 체크 상태와 저장 옵션에 맞춰 위쪽에 미리 표시합니다. 달라지는 값은 빨간 글씨로 표시합니다.\n미리보기 취소 시 위쪽만 원래 정보로 돌아가며 아래 편집 내용과 실제 파일은 변경하지 않습니다.',
  btnSaveCurrent:'오른쪽에 표시된 현재 한 곡을 저장합니다.\n체크한 태그 항목과 저장 옵션을 반영해 실제 음악 파일을 변경합니다.',
  btnSaveAll:'필터와 관계없이 체크된 자동선택 곡만 저장합니다. 확인필요·저장완료 곡은 제외합니다.',
  btnSaveSelected:'필터로 숨겨진 곡을 포함해 체크된 자동선택 곡만 저장합니다. 현재 곡 저장과 별도 범위입니다.',
  btnDiscard:'현재 곡의 미저장 편집을 버리고 편집 전 태그 값으로 돌아갑니다.\n이미 저장된 음악 파일은 변경하지 않습니다.',
  btnRestore:'주의: 실제 음악 파일을 최초 백업 당시의 내용으로 복원합니다.\n이후 저장한 변경도 되돌아갑니다. 편집 취소와 다른 기능입니다.',
  btnOptions:'빈 태그만 채우기, 가사 추가, 파일명 변경, 식별자 저장을 설정합니다.\n검색 국가·가수 표기·커버 크기도 여기서 설정합니다.'
};

Object.entries(buttonHelp).forEach(([id,text])=>{
  const button=$(id);button.setAttribute('aria-describedby','buttonTooltip');
  button.addEventListener('mouseenter',()=>showButtonTooltip(button,text));
  button.addEventListener('focus',()=>showButtonTooltip(button,text));
  button.addEventListener('mouseleave',hideButtonTooltip);button.addEventListener('blur',hideButtonTooltip);button.addEventListener('click',hideButtonTooltip);
});
const folderPathButton=$('folderToggle');
folderPathButton.setAttribute('aria-describedby','buttonTooltip');
folderPathButton.addEventListener('mouseenter',()=>showButtonTooltip(folderPathButton,pendingFolder||'전체'));
folderPathButton.addEventListener('focus',()=>showButtonTooltip(folderPathButton,pendingFolder||'전체'));
folderPathButton.addEventListener('mouseleave',hideButtonTooltip);folderPathButton.addEventListener('blur',hideButtonTooltip);folderPathButton.addEventListener('click',hideButtonTooltip);
document.addEventListener('keydown',e=>{if(e.key==='Escape')hideButtonTooltip();});
renderFileList();
loadPreferences();
loadFolders();
pollJobs();
pollSaveTasks();

/* #009: MA library results reuse the existing persisted job, file list and editor. */
const folderSearchNodes=[...$('scanControls').children].filter(el=>el.id!=='maSearchControls'&&!(el.contains($('searchSource'))));
function setSearchSource(value){
  const isMa=value==='ma';
  folderSearchNodes.forEach(el=>el.hidden=isMa);
  $('maSearchControls').hidden=!isMa;
  $('searchSource').value=value;
}
$('searchSource').addEventListener('change',()=>setSearchSource($('searchSource').value));
$('maSearchQuery').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();searchMaTracks();}});
$('maSearchButton').addEventListener('click',searchMaTracks);
async function searchMaTracks(){
  const query=$('maSearchQuery').value.trim();
  if(!query)return alert('검색어를 입력하세요');
  if(saving||searching||renameBusy)return;
  if(!await allowDraftMove())return;
  searching=true;$('maSearchButton').disabled=true;$('maSearchStatus').textContent='MA 검색 중…';
  try{
    const job=await api('/api/ma/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,field:$('maSearchField').value,limit:200})});
    viewPinned=true;currentJobId=job.id;adoptJob(job);lastDetailRevision=jobViewKey(job);
    $('maSearchStatus').textContent=job.total+'곡 검색됨 (실제 NAS 파일)';
    if(!job.total)$('statusLine').textContent='일치하는 NAS 음악 파일이 없습니다';
  }catch(e){$('maSearchStatus').textContent='검색 실패';alert(e.message);}
  finally{searching=false;$('maSearchButton').disabled=false;updateSavePreview();}
}
function showIdentifierValues(r){
  const ids=r.original?.ids||{};
  $('artistIdInput').value=r._artistIdEdited?r._manualArtistId:(ids.mb_artist_ids||[]).join('; ');
  $('albumArtistIdInput').value=r._albumArtistIdEdited?r._manualAlbumArtistId:(ids.mb_album_artist_ids||[]).join('; ');
  $('recordingIdDisplay').value=ids.mb_recording_id||'';
  $('itunesArtistIdDisplay').value=ids.itunes_artist_id||'';
  $('artistLookupPanel').hidden=true;
}
function editIdentifier(kind,value){
  if(!editingResult)return;
  const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const list=value.trim().split(/[;,]/).map(x=>x.trim()).filter(Boolean);
  const original=editingResult.original?.ids||{};
  const key=kind==='artist'?'mb_artist_ids':'mb_album_artist_ids';
  const changed=list.join(';')!==(original[key]||[]).join(';');
  if(changed&&(!list.length||list.length>10||list.some(x=>!uuid.test(x)))){
    $('artistLookupStatus').textContent='UUID 형식의 ID를 입력하세요';
    $('artistLookupPanel').hidden=false;
    return;
  }
  if(kind==='artist'){editingResult._artistIdEdited=changed;editingResult._manualArtistId=list.join(';');}
  else {editingResult._albumArtistIdEdited=changed;editingResult._manualAlbumArtistId=list.join(';');}
  if(changed){editingResult._selection='edit';editingResult._dirty=true;$('includeIds').checked=true;}
  updateSavePreview();
}
$('artistIdInput').addEventListener('change',e=>editIdentifier('artist',e.target.value));
$('albumArtistIdInput').addEventListener('change',e=>editIdentifier('albumartist',e.target.value));
let activeIdKind='artist';
async function lookupArtist(kind){
  if(!editingResult)return alert('먼저 곡을 선택하세요');
  activeIdKind=kind;
  const query=(kind==='artist'?$(chg_artist').value:$(chg_albumartist').value).trim();
  if(!query)return alert('가수 이름을 입력하세요');
  $('artistLookupPanel').hidden=false;
  $('artistLookupStatus').textContent='MusicBrainz 검색 중…';
  try{
    const data=await api('/api/musicbrainz/artists?query='+encodeURIComponent(query));
    const choices=$('artistLookupChoices');choices.replaceChildren();
    (data.artists||[]).forEach(a=>{
      const option=document.createElement('option');option.value=a.id;
      option.textContent=[a.name,a.disambiguation,a.country].filter(Boolean).join(' · ')+' — '+a.id;
      choices.append(option);
    });
    $('artistLookupStatus').textContent=choices.options.length+'건';
  }catch(e){$('artistLookupStatus').textContent=e.message;}
}
$('artistIdSearch').addEventListener('click',()=>lookupArtist('artist'));
$('albumArtistIdSearch').addEventListener('click',()=>lookupArtist('albumartist'));
$('artistLookupApply').addEventListener('click',()=>{
  const value=$('artistLookupChoices').value;if(!value)return;
  const field=activeIdKind==='artist'?'artistIdInput':'albumArtistIdInput';
  $(field).value=value;editIdentifier(activeIdKind,value);
  $('artistLookupPanel').hidden=true;
});
