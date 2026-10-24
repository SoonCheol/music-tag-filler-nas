// Reuse the existing isolated DOM harness with the actual page script.
const fs=require('node:fs'),assert=require('node:assert/strict');
const setup=fs.readFileSync('tests/test_p2_ui.js','utf8').split('(async()=>{')[0];
const harness=new Function('require',setup+'\nreturn harness;')(require);
const tick=async()=>{for(let i=0;i<24;i++)await Promise.resolve();};
function create(){
  const h=harness();h.context.job={id:'007',status:'done',results:[0,1].map(i=>({path:'song'+i+'.mp3',original:{title:'Original',artist:'Original singer',revision:'a'.repeat(64)},candidates:[{id:'A',title:'Song',artist:'Singer'},{id:'B',title:'Song',artist:'Singer',year:'2026'}]}))};
  h.$('candidateScroller').getBoundingClientRect=()=>({top:0,bottom:100});
  const createElement=h.context.document.createElement;
  h.context.document.createElement=tag=>Object.assign(createElement(tag),{getBoundingClientRect:()=>({top:200,bottom:220})});
  const original=h.context.fetch;let serial=0;h.lookups=[];
  h.context.fetch=async(url,options={})=>{
    if(url.endsWith('/candidate-lyrics')||url.endsWith('/lyrics-search')){
      const body=JSON.parse(options.body);h.lookups.push({url,body});
      return {ok:true,text:async()=>JSON.stringify(h.answer||{status:'found',lyrics:'Verified lyrics '+body.candidate_id,synced:'[00:00]Verified lyrics',lyrics_id:'token-'+ ++serial,query_title:body.title||'Song',query_artist:body.artist||'Singer'})};
    }
    return original(url,options);
  };
  h.run('adoptJob(job);selectFile(0)');return h;
}
(async()=>{
  const h=create();h.run('applyCandidate(editingResult,editingResult.candidates[0])');await tick();
  assert.equal(h.$('changeLyrics').value,'Verified lyrics A');assert.equal(h.$('changeLyrics').readOnly,false);
  assert.ok(h.run('saveItem(editingResult).lyrics_id'));assert.equal(h.lookups.length,1);
  h.run('applyCandidate(editingResult,editingResult.candidates[0])');await tick();assert.equal(h.lookups.length,1);
  h.run('renderCandidates(editingResult)');
  const generation=h.run('candidateListGeneration');h.$('candidateLyrics'+generation+'-0').onclick({stopPropagation(){}});await tick();
  assert.equal(h.lookups.length,2);assert.equal(h.lookups[1].body.candidate_id,'A');assert.equal(h.lookups[1].body.force,true);
  h.$('changeLyrics').value='User edited lyrics';h.$('changeLyrics').listeners.input();
  const oldToken=h.run('editingResult._lyricsSearch.lyrics_id');await h.run('searchLyricsForCurrent()');await tick();
  assert.equal(h.lookups.at(-1).body.force,true);assert.equal(h.$('changeLyrics').value,'User edited lyrics');
  assert.equal(h.run('saveItem(editingResult).lyrics_id'),oldToken);assert.equal(h.run('saveItem(editingResult).lyrics_text'),'User edited lyrics');
  assert.equal(h.run('editingResult._lyricsSearch.synced'),'');
  h.$('changeLyrics').value='';h.$('changeLyrics').listeners.input();
  h.run('applyCandidate(editingResult,editingResult.candidates[1])');await tick();assert.equal(h.$('changeLyrics').value,'');
  assert.equal(h.run('editingResult._lyricsEdited'),true);
  console.log('PASS: cached auto input, editable draft, L force only one candidate, manual force, user edits/deletion protected');

  const stale=create();let release;const oldFetch=stale.context.fetch;
  stale.context.fetch=(url,options)=>url.endsWith('/candidate-lyrics')?new Promise(resolve=>release=resolve):oldFetch(url,options);
  stale.run('applyCandidate(editingResult,editingResult.candidates[0]);selectFile(1)');
  release({ok:true,text:async()=>JSON.stringify({status:'found',lyrics:'Late A',lyrics_id:'late'})});await tick();
  assert.equal(stale.$('changeLyrics').value,'');assert.equal(stale.run('editingResult.path'),'song1.mp3');
  console.log('PASS: late response cannot paint another file');

  const none=create();none.run('applyCandidate(editingResult,editingResult.candidates[0])');await tick();
  none.answer={status:'not_found',lyrics:'',lyrics_id:'none'};
  none.run('applyCandidate(editingResult,editingResult.candidates[1])');await tick();
  assert.equal(none.run('editingResult._lyricsSearch.lyrics'),'Verified lyrics A');
  assert.equal(none.$('changeLyrics').value,'Verified lyrics A');
  assert.equal(none.run('saveItem(editingResult).lyrics_id'),null);
  console.log('PASS: no-result preserves previous draft without reusing another candidate token');

  const protectedUI=create();protectedUI.$('onlyEmpty').checked=true;
  protectedUI.run('editingResult.original.has_lyrics=true;applyCandidate(editingResult,editingResult.candidates[0])');await tick();
  assert.equal(protectedUI.lookups.length,0);assert.equal(protectedUI.$('changeLyrics').readOnly,true);
  console.log('PASS: existing lyrics protected by only-empty');

  const scheduler=create();const pending=[];
  scheduler.context.fetch=(url,options)=>new Promise(resolve=>pending.push({url,resolve}));
  scheduler.run("mediaJobStatus='scanning';requestCandidateLyrics(job.results[0].candidates[0],job.results[0]);requestCandidateLyrics(job.results[0].candidates[1],job.results[0])");
  assert.equal(pending.length,0);
  scheduler.run("mediaJobStatus='done';pumpCandidateMedia();requestCandidateCover({id:'C',album:'Album'},job.results[1]);requestCandidateLyrics(job.results[0].candidates[0],job.results[0])");
  assert.equal(pending.length,2);assert.equal(scheduler.run('candidateCoverRunning+candidateLyricsRunning'),2);
  scheduler.run('stopMediaPrefetch()');assert.equal(scheduler.run('candidateCoverQueue.length+candidateLyricsQueue.length'),0);
  console.log('PASS: scan blocks prefetch, total media concurrency <=2, dedupe, queued work cancelled');
})().catch(error=>{console.error(error);process.exitCode=1;});
