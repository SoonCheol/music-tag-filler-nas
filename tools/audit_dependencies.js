// Optional public-package audit. Sends only PyPI names/versions, never NAS data.
const fs = require('node:fs');
const https = require('node:https');
if (!process.argv.includes('--online')) {
  console.error('Use --online to query OSV. Optional: --output docs/dependency-audit.json');
  process.exit(2);
}
function request(endpoint, value) {
  return new Promise((resolve, reject) => {
    const body = value ? JSON.stringify(value) : '';
    const headers = {'User-Agent': 'music-tag-filler-dependency-audit'};
    if (value) Object.assign(headers, {'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)});
    const req = https.request('https://api.osv.dev' + endpoint, {method:value?'POST':'GET',headers,timeout:20000}, res => {
      let text='';res.on('data',d=>text+=d);res.on('end',()=>{
        if(res.statusCode!==200)return reject(new Error('OSV HTTP '+res.statusCode));
        try{resolve(JSON.parse(text));}catch{reject(new Error('Invalid OSV JSON'));}
      });
    });
    req.on('timeout',()=>req.destroy(new Error('OSV timeout')));req.on('error',reject);req.end(body);
  });
}
(async()=>{
  const packages=fs.readFileSync('requirements.lock.txt','utf8').split(/\r?\n/).filter(l=>l&&!l.startsWith('#')).map(l=>{
    const match=l.match(/^([\w.-]+)==([\w.+!-]+)$/);if(!match)throw new Error('Only pinned public package versions accepted');
    return {name:match[1],version:match[2]};
  });
  const initial=await request('/v1/querybatch',{queries:packages.map(p=>({package:{name:p.name,ecosystem:'PyPI'},version:p.version}))});
  if(initial.results?.length!==packages.length)throw new Error('Incomplete batch response');
  for(let i=0;i<packages.length;i++){
    let page=initial.results[i];const ids=new Set((page.vulns||[]).map(v=>v.id));
    while(page.next_page_token){page=await request('/v1/query',{package:{name:packages[i].name,ecosystem:'PyPI'},version:packages[i].version,page_token:page.next_page_token});for(const v of page.vulns||[])ids.add(v.id);}
    packages[i].vulnerabilityIds=[...ids];
  }
  const ids=[...new Set(packages.flatMap(p=>p.vulnerabilityIds))],details=[];
  for(let i=0;i<ids.length;i+=4){
    const group=await Promise.all(ids.slice(i,i+4).map(id=>request('/v1/vulns/'+encodeURIComponent(id))));
    details.push(...group.map(d=>({id:d.id,aliases:d.aliases||[],summary:d.summary||'',withdrawn:d.withdrawn||null,
      severity:d.database_specific?.severity||null,url:'https://osv.dev/vulnerability/'+d.id,
      affected:(d.affected||[]).filter(a=>a.package?.ecosystem==='PyPI').map(a=>({package:a.package.name,
        fixed:[...new Set((a.ranges||[]).flatMap(r=>(r.events||[]).filter(e=>e.fixed).map(e=>e.fixed)))]}))})));
  }
  const report={checkedAt:new Date().toISOString(),source:'https://api.osv.dev',scope:'Public PyPI names and pinned versions only; not an exploitability assessment or OS-image audit',packages,advisories:details};
  const outputIndex=process.argv.indexOf('--output');
  if(outputIndex!==-1){if(!process.argv[outputIndex+1])throw new Error('Missing output path');fs.writeFileSync(process.argv[outputIndex+1],JSON.stringify(report,null,2)+'\n');}
  console.log(JSON.stringify({packages:packages.length,flaggedPackages:packages.filter(p=>p.vulnerabilityIds.length).map(p=>({name:p.name,version:p.version,advisoryIds:p.vulnerabilityIds})),uniqueAdvisories:ids.length},null,2));
})().catch(e=>{console.error('Audit incomplete: '+e.message);process.exitCode=1;});
