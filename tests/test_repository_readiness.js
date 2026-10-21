// Read-only completeness/privacy check for the files eligible for the next commit.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const required = [
  'README.md', 'AGENTS.md', 'CHANGELOG.md', '.gitignore', '.dockerignore',
  'Dockerfile', 'requirements.txt', 'requirements.lock.txt', 'portainer-stack.yml',
  'docker-compose.yml', 'deploy-nas.ps1', 'deploy-nas.example.json', 'DEPLOYMENT.md',
  'docs/CURRENT_NAS.md', 'docs/INSTALL_KO.md', 'docs/OPERATIONS_KO.md',
  'docs/BACKUP_RESTORE_KO.md', 'docs/READINESS_REPORT.md', 'THIRD_PARTY_NOTICES.md',
  'app/upstream/LICENSE', 'app/upstream/NOTICE.md', 'licenses/LGPL-2.1.txt',
  'licenses/GPL-2.txt', 'licenses/GPL-3.txt', 'licenses/Debian-Chromaprint-copyright.txt',
  'licenses/Debian-FFmpeg-copyright.txt', '.github/workflows/ci.yml',
  'tests/test_p0_storage.py', 'tests/test_p1_search.py', 'tests/test_p2_workflow.py',
  'tests/test_ui_save.js', 'tests/test_p2_ui.js', 'tests/test_gitignore.js',
  'tests/deploy-nas.tests.ps1', 'tests/test_repository_readiness.js',
  'docs/SECURITY_AUDIT_KO.md', 'docs/dependency-audit.json', 'tools/audit_dependencies.js',
  'docs/RELEASE_V1_0_0.md',
];
const candidates = [...new Set(cp.execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '-z'],
  {encoding:'utf8'}).split('\0').filter(Boolean))];
for (const name of required) {
  assert(fs.statSync(name).size > 0, 'Missing/empty recovery file: ' + name);
  assert(candidates.includes(name), 'Recovery file excluded from Git: ' + name);
}
const script = fs.readFileSync('deploy-nas.ps1', 'utf8');
const deploymentFiles = [...script.match(/\$files = @\(([\s\S]*?)\)\r?\n/)[1].matchAll(/'([^']+)'/g)].map(m=>m[1]);
for (const file of deploymentFiles) assert(fs.existsSync(file), 'Deployment input missing: ' + file);
for (const file of candidates.filter(f=>f.startsWith('app/') && !/(?:main_1|main_new|index_1|index_new)\./.test(f)))
  assert(deploymentFiles.includes(file), 'Active app artifact omitted from deployment: ' + file);
for (const file of ['Dockerfile', 'requirements.txt', 'requirements.lock.txt', '.dockerignore'])
  assert(deploymentFiles.includes(file), 'Build input omitted from deployment: ' + file);
const locked = new Map(fs.readFileSync('requirements.lock.txt','utf8').split(/\r?\n/).filter(l=>l&&!l.startsWith('#'))
  .map(l=>l.split('==')).map(([n,v])=>[n.toLowerCase().replaceAll('_','-'),v]));
for(const line of fs.readFileSync('requirements.txt','utf8').split(/\r?\n/).filter(Boolean)){
  const [name,version]=line.split('==');assert.equal(locked.get(name.replace(/\[.*\]/,'').toLowerCase().replaceAll('_','-')),version,'Direct dependency/lock mismatch');
}
const dockerfile=fs.readFileSync('Dockerfile','utf8');assert(dockerfile.includes('-c requirements.lock.txt'));
const normalizeYaml=f=>fs.readFileSync(f,'utf8').split(/\r?\n/).filter(l=>!l.startsWith('#')).join('\n').trim();
assert.equal(normalizeYaml('docker-compose.yml'),normalizeYaml('portainer-stack.yml'),'Canonical Stack/Compose differ');
const stack=normalizeYaml('portainer-stack.yml');assert(stack.includes('read_only: false'));
assert(script.includes('MusicReadOnly must be a JSON boolean.'));
assert(script.includes('mount mode differs from configured MusicReadOnly'));
const riskyNames=/(^|\/)(?:data|backups|deploy-backups|\.ssh|\.aws)(?:\/|$)|\.local\.|\.(?:mp3|flac|m4a|ogg|wav|wma|mp4|pem|pfx|key|db|sqlite|bak|zip|tar|bundle|enc)$|(?:^|\/)(?:settings|jobs)\.json$|acoustid_key\.txt$|tagbak/i;
const secretPatterns=[/-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----/,
  /\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{30,})\b/,
  /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/,/https?:\/\/[^\s/@:]+:[^\s/@]+@/];
for(const file of candidates){
  assert(!riskyNames.test(file),'Private/runtime file eligible for upload: '+file);
  const text=fs.readFileSync(file,'utf8');
  text.split(/\r?\n/).forEach((line,i)=>{
    // An intentional invalid URL tests credential rejection, never a real credential.
    const fixtureUrl=['https:','//','user:password@','example.invalid'].join('');
    const safeLine=file==='tests/deploy-nas.tests.ps1'?line.replace(fixtureUrl,''):line;
    assert(!secretPatterns.some(re=>re.test(safeLine)),`Possible credential at ${file}:${i+1}; value suppressed`);
  });
  if(file.endsWith('.md'))for(const link of text.matchAll(/\[[^\]]*\]\(([^)]+)\)/g)){
    const target=link[1];if(/^(?:https?:|#|[A-Za-z]:)/.test(target)||target.includes('<'))continue;
    assert(fs.existsSync(path.resolve(path.dirname(file),target.split('#')[0])),`Broken document link in ${file}: ${target}`);
  }
}
console.log(`PASS: ${required.length} required files, ${deploymentFiles.length} deployment inputs, ${locked.size} dependency constraints, document links and ${candidates.length} upload candidates checked. Operational metadata is owner-authorized; secrets/runtime originals are excluded.`);
