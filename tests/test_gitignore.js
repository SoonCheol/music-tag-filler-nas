// Test ignore rules without creating any credential or music files.
const assert = require('node:assert/strict');
const cp = require('node:child_process');
const blocked = [
  'deploy-nas.local.json', 'custom/environment.local.json', '.env', '.env.production',
  '.ssh/id_rsa', 'id_ed25519', 'secret.pem', 'private.key', 'certificate.pfx', 'key.txt',
  'passwords.txt', 'api_key.txt', 'acoustid_key.txt', 'credentials.json', 'secrets.json',
  '.git-credentials', '.netrc', '.aws/credentials', '.codex/auth.json',
  'settings.json', 'nested/settings.local.json', 'jobs.json', 'data/state.json',
  'backups/original.bin', 'deploy-backups/config.yml', 'track.mp3.tagbak.json', 'saved.bak',
  'music/song.mp3', 'song.MP3', 'song.FLAC', 'song.m4a', 'song.OGG', 'song.wav',
  'song.wma', 'song.mp4', 'song.aac', 'song.aiff', 'song.opus', 'song.dsf',
  'scratch/anything', 'uploads/cover.jpg', 'pending-covers/cover.jpg', 'archive.zip',
  'repository.bundle', 'backup.sql', 'data.dump', 'private-backup.enc',
];
const allowed = ['.gitignore', 'AGENTS.md', 'README.md', 'DEPLOYMENT.md', 'deploy-nas.ps1',
  'deploy-nas.example.json', '.env.example', 'Dockerfile', 'docker-compose.yml',
  'requirements.txt', 'app/main.py', 'app/preferences.py', 'app/search_service.py',
  'app/static/index.html', 'app/upstream/LICENSE', 'tests/test_gitignore.js',
  'tests/test_p0_storage.py', 'tests/deploy-nas.tests.ps1'];
const result = cp.spawnSync('git', ['check-ignore', '--no-index', '--stdin', '-z'], {
  input: [...blocked, ...allowed].join('\0') + '\0', encoding: 'utf8', windowsHide: true,
});
assert([0, 1].includes(result.status), 'git check-ignore failed');
const ignored = new Set(result.stdout.split('\0').filter(Boolean));
for (const name of blocked) assert(ignored.has(name), 'Unprotected private/runtime path: ' + name);
for (const name of allowed) assert(!ignored.has(name), 'Source/example unexpectedly ignored: ' + name);
console.log(`PASS: ${blocked.length} private/runtime/music paths excluded; ${allowed.length} source/example paths retained.`);
