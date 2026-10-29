// Preferences, option dialogs, confirmations and tooltips.
// Definitions only; shared state and ordered startup live in app.js.

function confirmAction(title,message,acceptLabel,cancelLabel='취소'){
  if(actionResolver)return Promise.resolve(false);
  $('actionTitle').textContent=title;$('actionMessage').textContent=message;
  $('actionAccept').textContent=acceptLabel;$('actionCancel').textContent=cancelLabel;
  return new Promise(resolve=>{actionResolver=resolve;$('actionDialog').showModal();$('actionCancel').focus();});
}

function resolveAction(accepted){
  const resolve=actionResolver;actionResolver=null;$('actionDialog').close();if(resolve)resolve(accepted);
}

function preferenceValues(){return {country:$('searchCountry').value,use_fingerprint:$('useFingerprint').checked,recurse:$('recurse').checked,only_empty:$('onlyEmpty').checked,fill_lyrics:$('fillLyrics').checked,save_synced:$('saveSynced').checked,create_lrc:$('createLrc').checked,rename:false,include_ids:$('includeIds').checked,artist_name_preference:$('artistPreference').value,cover_max_px:Number($('coverMax').value)};}

async function loadPreferences(){try{const p=await api('/api/preferences');$('searchCountry').value=p.country;if(typeof p.use_fingerprint==='boolean')$('useFingerprint').checked=p.use_fingerprint;$('recurse').checked=p.recurse;$('onlyEmpty').checked=p.only_empty;$('fillLyrics').checked=p.fill_lyrics;$('saveSynced').checked=!!p.save_synced;$('createLrc').checked=!!p.create_lrc;$('renameFiles').checked=false;$('includeIds').checked=p.include_ids;$('artistPreference').value=p.artist_name_preference;$('coverMax').value=p.cover_max_px;}catch(e){$('statusLine').textContent='설정 읽기 실패: '+e.message;}finally{$('btnOptions').disabled=false;updateSavePreview();}}

function refreshCandidatePreference(){
  captureCurrent();
  currentResults.forEach(r=>{
    if(!r._draft)return;
    const c=r.candidates?.find(c=>c.id===r._candidateId);if(!c)return;
    const latin=$('artistPreference').value==='latin';
    const values={artist:latin?(c.artist_latin||c.artist):c.artist,albumartist:latin?(c.album_artist_latin||c.albumartist):c.albumartist};
    Object.entries(values).forEach(([f,value])=>{if(value&&!protectedField(r,f)&&!(r._manualFields||[]).includes(f))r._draft[f]=String(value);});
  });
  if(editingResult)tagFields.forEach(f=>$('chg_'+f).value=editingResult._draft[f]);
}

function optionState(){return Object.fromEntries(modalOptionIds.map(id=>[id,modalCheckboxIds.includes(id)?$(id).checked:$(id).value]));}

function openSaveOptions(){if(optionsSnapshot)return;closeFolderMenu();optionsSnapshot=optionState();$('rememberOptions').checked=false;$('saveOptionsDialog').showModal();}

function cancelSaveOptions(){if(!optionsSnapshot)return;modalOptionIds.forEach(id=>{if(modalCheckboxIds.includes(id))$(id).checked=optionsSnapshot[id];else $(id).value=optionsSnapshot[id];});optionsSnapshot=null;$('saveOptionsDialog').close();updateSavePreview();}

async function applySaveOptions(event){event.preventDefault();if(!optionsSnapshot||!$('saveOptionsForm').reportValidity())return;const remember=$('rememberOptions').checked;optionsSnapshot=null;$('saveOptionsDialog').close();refreshCandidatePreference();updateSavePreview();if(remember)await savePreferences();}

async function savePreferences(){try{await api('/api/preferences',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(preferenceValues())});alert('옵션을 기억했습니다');}catch(e){alert('설정 저장 실패: '+e.message);}}

async function showDiagnostics(){try{const d=await api('/api/diagnostics?check_network=true');alert(JSON.stringify(d,null,2));}catch(e){alert('진단 실패: '+e.message);}}

function hideButtonTooltip(){$('buttonTooltip').hidden=true;}

function showButtonTooltip(button,text){
  const tip=$('buttonTooltip');tip.textContent=text;tip.hidden=false;
  const rect=button.getBoundingClientRect(),size=tip.getBoundingClientRect();
  tip.style.left=Math.max(12,Math.min(rect.left,window.innerWidth-size.width-12))+'px';
  tip.style.top=Math.max(12,rect.top-size.height-8>=12?rect.top-size.height-8:Math.min(rect.bottom+8,window.innerHeight-size.height-12))+'px';
}
