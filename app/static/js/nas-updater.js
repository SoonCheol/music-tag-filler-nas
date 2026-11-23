/* Portable opt-in update panel. No secrets are persisted or embedded in HTML. */
(() => {
  const el=id=>document.getElementById(id);
  const panel=el('updaterPanel');
  if(!panel)return;
  const state=el('updateStatus'),current=el('updateCurrent'),latest=el('updateLatest');
  const check=el('updateCheck'),apply=el('updateApply');
  let known=null,pollTimer=null,busy=false;
  function text(value){state.textContent=value;}
  function stop(){if(pollTimer)clearTimeout(pollTimer);pollTimer=null;}
  async function request(path,method='GET',body=null){
    const opts={method,cache:'no-store',headers:{}};
    if(method==='POST'){
      opts.headers={'Content-Type':'application/json','X-Requested-With':'NAS-Updater'};
      opts.body=JSON.stringify(body);
    }
    const response=await fetch('/api/updater/'+path,opts);
    let result;
    try{result=await response.json();}catch(e){throw new Error('서버 응답 형식이 올바르지 않습니다.');}
    if(!response.ok)throw new Error(result.detail||'요청 실패');
    return result;
  }
  function display(value){
    known=value;
    current.textContent=value.current_label||value.current||'알 수 없음';
    latest.textContent=value.latest||'알 수 없음';
    apply.disabled=!value.available||!value.ready;
    stop();
    if(value.task&&['queued','running'].includes(value.task.state)){
      apply.disabled=true;
      text(value.task.phase||'업데이트 진행 중');
      if(panel.open)pollTimer=setTimeout(()=>refresh(true),3500);
    }else if(value.task?.state==='failed')text('업데이트 실패: '+value.task.phase);
    else if(value.task?.state==='done')text('새 이미지가 적용됐습니다. 페이지를 새로고침해 확인하세요.');
    else if(!value.ready)text('업데이트 관리자 암호 설정이 필요합니다.');
    else text(value.message||'확인 완료');
  }
  async function refresh(automatic=false){
    if(busy)return;
    busy=true;check.disabled=true;
    try{display(await request('status'));}
    catch(e){apply.disabled=true;text('확인 실패: '+e.message);if(!automatic)known=null;}
    finally{busy=false;check.disabled=false;}
  }
  panel.addEventListener('toggle',()=>{if(panel.open)refresh();else stop();});
  check.addEventListener('click',()=>refresh());
  apply.addEventListener('click',async()=>{
    if(!known||!known.available||!known.ready)return;
    if(!window.confirm('현재 '+known.current+'에서 '+known.latest+' 빌드로 업데이트할까요? 음악 작업이 진행 중이면 취소됩니다.'))return;
    const password=window.prompt('업데이트 관리자 암호 (입력한 암호는 저장하지 않습니다)');
    if(!password)return;
    apply.disabled=true;
    try{
      await request('apply','POST',{expected_current:known.current,expected_latest:known.latest_sha,password});
      text('업데이트 요청 접수됨. 진행 결과 확인 중…');
      stop();pollTimer=setTimeout(()=>refresh(true),2500);
    }catch(e){text('업데이트 시작 실패: '+e.message);apply.disabled=false;}
  });
})();
