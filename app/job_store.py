"""Independent atomic job records; legacy history is archived without migration."""
import json
from pathlib import Path
import re
import threading
import time
from . import storage, job_service, rename_service

_lock = threading.RLock()
_cache = {}

def record_path(root, job_id):
    if not isinstance(job_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',job_id):
        raise OSError('유효하지 않은 작업 ID')
    folder=Path(root)/'jobs'
    if folder.is_symlink():
        raise OSError('작업 기록 폴더는 심볼릭 링크일 수 없습니다')
    return folder/(job_id+'.json')

def load(root):
    root=Path(root)
    with _lock:
        legacy=root/'jobs.json'
        if legacy.exists() or legacy.is_symlink():
            if legacy.is_symlink():raise OSError('기존 작업 기록 링크는 보관할 수 없습니다')
            old=json.loads(legacy.read_text(encoding='utf-8-sig'))
            if not isinstance(old,dict) or any(not isinstance(j,dict) for j in old.values()):
                raise ValueError('유효하지 않은 기존 작업 기록')
            if any(j.get('status') in job_service.ACTIVE for j in old.values()):
                raise OSError('진행 중인 기존 작업이 있어 새 기록 구조로 전환할 수 없습니다')
            rename_service.no_replace(legacy,root/'jobs_legacy.json')
        result={}
        folder=root/'jobs'
        if folder.is_symlink():raise OSError('작업 기록 폴더 링크는 허용하지 않습니다')
        for path in sorted(folder.glob('*.json')):
            if path.is_symlink() or not path.is_file():raise OSError('유효하지 않은 작업 기록 파일')
            value=json.loads(path.read_text(encoding='utf-8'))
            if value.get('id')!=path.stem or record_path(root,path.stem)!=path:raise ValueError('작업 ID와 기록 이름 불일치')
            _cache[(str(root.resolve()),path.stem)]=storage.digest(storage._json_bytes(value))
            result[path.stem]=value
        return job_service.normalize_jobs(result)

def save(root,jobs,ids=None):
    root=Path(root)
    with _lock:
        for job_id in list(jobs) if ids is None else ids:
            value=jobs[job_id];path=record_path(root,job_id)
            if path.is_symlink():raise OSError('작업 기록 링크는 덮어쓰지 않습니다')
            data=storage._json_bytes(value);key=(str(root.resolve()),job_id);checksum=storage.digest(data)
            if _cache.get(key)==checksum and path.is_file():continue
            value["record_version"]=time.time_ns()
            data=storage._json_bytes(value);checksum=storage.digest(data)
            created_folder=not path.parent.exists()
            path.parent.mkdir(exist_ok=True)
            if created_folder:rename_service.sync_dir(root)
            storage._replace_file(path,data)
            # _replace_file already syncs the publication directory.
            _cache[key]=checksum

def delete(root,ids):
    # Only named job JSON files; music and backup paths are never accepted.
    with _lock:
        for job_id in ids:
            path=record_path(root,job_id)
            if path.is_symlink():raise OSError('작업 기록 링크는 삭제하지 않습니다')
            path.unlink(missing_ok=True)
            if path.parent.exists():rename_service.sync_dir(path.parent)
            _cache.pop((str(Path(root).resolve()),job_id),None)
