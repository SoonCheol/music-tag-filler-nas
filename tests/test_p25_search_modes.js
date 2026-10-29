// Focused UI state check for search-mode submission and preserving local drafts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app/static/js/search-list.js'), 'utf8');
const start = source.indexOf('async function manualSearch(');
assert.notEqual(start, -1);
const functionSource = source.slice(start).trim();
assert.match(functionSource, /^async function manualSearch\(/);

(async () => {
  const elements = new Map();
  const $ = id => {
    if (!elements.has(id)) elements.set(id, {value: '', textContent: '', hidden: false});
    return elements.get(id);
  };
  $('searchMode').value = 'quick';
  const row = {
    path: 'Singer - Song.mp3', _draftRevision: 'a'.repeat(64),
    _candidateId: 'user-choice', _selection: 'manual',
    _draft: {title: 'Edited title', artist: 'Edited artist'},
    _fields: ['title', 'artist'], _manualFields: ['title'],
    _lyricsSearch: {lyrics_id: 'lyrics-choice'}, _lyricsDraft: 'Unfinished lyric draft',
    _lyricsEdited: true, _lyricsEpoch: 4, _dirty: true,
    _coverId: 'cover-choice', _checked: true,
  };
  let request;
  const context = vm.createContext({
    $, editingResult: row, filteredResults: [row], currentJobId: 'job',
    saving: false, searching: false, captureCurrent() {},
    updateSavePreview() {},
    async api(_url, options) {
      request = JSON.parse(options.body);
      return {candidates: [{id: 'new-result'}], musicbrainz_skipped: false, search_status: 'matched'};
    },
    selectFile() {}, searchSummary: () => '검색 완료', alert() {},
  });
  vm.runInContext(functionSource, context);
  await vm.runInContext("manualSearch('integrated')", context);
  assert.equal(request.search_mode, 'integrated');
  assert.equal(request.preserve_candidate_id, 'user-choice');
  assert.equal(row._candidateId, 'user-choice');
  assert.equal(row._selection, 'manual');
  assert.equal(row._draft.title, 'Edited title');
  assert.equal(row._draft.artist, 'Edited artist');
  assert.equal(row._lyricsSearch.lyrics_id, 'lyrics-choice');
  assert.equal(row._lyricsDraft, 'Unfinished lyric draft');
  assert.equal(row._lyricsEdited, true);
  assert.equal(row._coverId, 'cover-choice');
  assert.equal(row._checked, true);
  console.log('PASS: manual search sends the selected provider mode and retains candidate, tag, lyric, and cover drafts.');
})().catch(error => { console.error(error); process.exitCode = 1; });
