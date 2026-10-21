"""Optional live metadata probe; run isolated, with no production volumes."""
import json
from pathlib import Path
from app import search_service as service
from app.upstream import search_lyrics as lyrics

result = service.search(Path('/tmp/not-an-audio-file'), 'The Beatles - Yesterday', 'US', 125,
                        Path('/tmp/probe-settings'), use_fingerprint=False)
print(json.dumps({'status': result['search_status'], 'count': len(result['candidates']),
                  'sources': sorted({s for c in result['candidates'] for s in c['sources']}),
                  'errors': result['search_errors']}, ensure_ascii=False), flush=True)
found = lyrics.find('Yesterday', 'The Beatles', 125)
print(json.dumps({'lyrics_status': found.status, 'lyrics_characters': len(found.text)}), flush=True)
if result['candidates']:
    cover, errors = service.fetch_cover(result['candidates'][0], 'US')
    print(json.dumps({'cover_bytes': len(cover or b''), 'errors': errors}), flush=True)
