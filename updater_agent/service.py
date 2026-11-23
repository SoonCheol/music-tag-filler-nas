"""Shared NAS updater: allowlisted apps, immutable GHCR tags, Portainer stack image-only change."""
import copy
import hmac
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote

import requests
import yaml
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

app = FastAPI(title="NAS Update Agent", docs_url=None, redoc_url=None, openapi_url=None)
SHA = re.compile(r"^[0-9a-f]{40}$")
NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
LOCK = threading.Lock()
task = None


def load_apps(path):
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj.get("apps"), list):
        raise ValueError("apps array is required")
    apps = {}
    keys = ("id", "repo", "workflow", "branch", "image_repo", "stack_id", "endpoint_id", "stack", "service", "safety_url")
    for entry in obj["apps"]:
        if not isinstance(entry, dict) or any(k not in entry for k in keys):
            raise ValueError("incomplete allowlist")
        if (not NAME.fullmatch(entry["id"]) or entry["id"] in apps
                or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", entry["repo"])
                or not IMAGE.fullmatch(entry["image_repo"])
                or not all(NAME.fullmatch(entry[k]) for k in ("workflow", "branch", "stack", "service"))
                or not all(type(entry[k]) is int and entry[k] > 0 for k in ("stack_id", "endpoint_id"))
                or not entry["safety_url"].startswith(("http://", "https://"))):
            raise ValueError("invalid updater allowlist")
        legacy = entry.get("legacy_images", [])
        if not isinstance(legacy, list) or any(not isinstance(x, str) or not IMAGE.fullmatch(x) for x in legacy):
            raise ValueError("invalid legacy images")
        # Optional versioning: per-app version sequence is based on GitHub Actions run_number.
        prefix = entry.get("version_prefix")
        baseline = entry.get("version_base_run")
        if (prefix is None) != (baseline is None):
            raise ValueError("incomplete version settings")
        if prefix is not None and (not isinstance(prefix, str) or not re.fullmatch(r"\d+\.\d+", prefix)
                                   or type(baseline) is not int or baseline < 0):
            raise ValueError("invalid version settings")
        apps[entry["id"]] = entry
    return apps


try:
    APPS = load_apps(os.getenv("UPDATER_CONFIG", "/config/apps.json"))
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    APPS = {}

try:
    KEYS = json.loads(os.getenv("UPDATER_APP_KEYS_JSON", "{}"))
except ValueError:
    KEYS = {}
if not isinstance(KEYS, dict):
    KEYS = {}


def equal(a, b):
    return isinstance(a, str) and isinstance(b, str) and bool(a) and bool(b) and hmac.compare_digest(a, b)


def authorize(app_id, request):
    if app_id not in APPS:
        raise HTTPException(404, "등록되지 않은 앱입니다.")
    if not equal(request.headers.get("x-app-key", ""), KEYS.get(app_id, "")):
        raise HTTPException(403, "앱 인증에 실패했습니다.")
    return APPS[app_id]


def portainer(method, path, body=None):
    base = os.getenv("PORTAINER_URL", "").rstrip("/")
    key = os.getenv("PORTAINER_API_KEY", "")
    if not base.startswith(("http://", "https://")) or not key:
        raise RuntimeError("Portainer 연결 설정이 없습니다.")
    try:
        response = requests.request(method, base + "/api" + path,
                                    headers={"X-API-Key": key}, json=body,
                                    timeout=50 if method == "PUT" else 15)
        response.raise_for_status()
        return response.json() if response.content else {}
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError("Portainer API 요청 실패") from exc


def latest_build(cfg):
    key = os.getenv("GITHUB_READ_TOKEN", "")
    if not key:
        raise RuntimeError("GitHub Actions 읽기 토큰이 없습니다.")
    url = ("https://api.github.com/repos/" + cfg["repo"] + "/actions/workflows/"
           + quote(cfg["workflow"], safe="") + "/runs")
    try:
        response = requests.get(url, params={"branch": cfg["branch"], "status": "success", "per_page": 30},
                                headers={"Authorization": "Bearer " + key, "Accept": "application/vnd.github+json"},
                                timeout=15)
        response.raise_for_status()
        runs = response.json()["workflow_runs"]
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        raise RuntimeError("GitHub 최신 빌드 조회 실패") from exc
    for run in runs:
        sha = str(run.get("head_sha", "")).lower()
        if (run.get("head_branch") == cfg["branch"] and run.get("conclusion") == "success"
                and run.get("event") in ("push", "workflow_dispatch") and SHA.fullmatch(sha)):
            run_number = run.get("run_number")
            if type(run_number) is int and run_number > 0:
                return sha, run_number
    raise RuntimeError("배포 가능한 성공 빌드가 없습니다.")


def current_stack(cfg):
    stack = portainer("GET", "/stacks/" + str(cfg["stack_id"]))
    if (stack.get("Id") != cfg["stack_id"] or stack.get("EndpointId") != cfg["endpoint_id"]
            or stack.get("Name") != cfg["stack"] or stack.get("Type") != 2
            or stack.get("GitConfig") or stack.get("gitConfig")):
        raise RuntimeError("허용된 스택과 실제 스택이 다릅니다.")
    raw = portainer("GET", "/stacks/" + str(cfg["stack_id"]) + "/file").get("StackFileContent")
    if not isinstance(raw, str):
        raise RuntimeError("기존 스택 원본을 읽을 수 없습니다.")
    model = yaml.safe_load(raw)
    if not isinstance(model, dict) or not isinstance(model.get("services"), dict):
        raise RuntimeError("잘못된 Compose 구조입니다.")
    if set(model["services"]) != {cfg["service"]}:
        raise RuntimeError("다른 서비스가 포함된 스택은 변경하지 않습니다.")
    service = model["services"][cfg["service"]]
    image = service.get("image") if isinstance(service, dict) else None
    if not isinstance(image, str) or ":" not in image or "@" in image:
        raise RuntimeError("고정 이미지 태그가 없습니다.")
    if image.rsplit(":", 1)[0] not in [cfg["image_repo"]] + cfg.get("legacy_images", []):
        raise RuntimeError("허용되지 않은 이미지 저장소입니다.")
    return stack, raw, model, image


def patched_stack(raw, model, service, image):
    old = model["services"][service]["image"]
    lines = raw.splitlines(keepends=True)
    found = []
    for i, line in enumerate(lines):
        if line.strip() in ("image: " + old, "image: '" + old + "'", 'image: "' + old + '"'):
            found.append(i)
    if len(found) != 1:
        raise RuntimeError("이미지 행을 안전하게 식별할 수 없습니다.")
    i = found[0]
    lines[i] = lines[i].replace(old, image, 1)
    output = "".join(lines)
    expected = copy.deepcopy(model)
    expected["services"][service]["image"] = image
    if yaml.safe_load(output) != expected:
        raise RuntimeError("이미지 외 스택 설정 변경이 감지됐습니다.")
    return output


def safety_check(cfg):
    try:
        response = requests.get(cfg["safety_url"], headers={"X-Updater-Key": KEYS[cfg["id"]]}, timeout=8)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        raise RuntimeError("앱의 안전 상태를 확인하지 못했습니다.") from exc
    if data.get("safe") is not True:
        raise RuntimeError(data.get("reason") or "진행 중인 작업이 있습니다.")


def status(cfg):
    _, _, _, current = current_stack(cfg)
    sha, run_number = latest_build(cfg)
    prefix = cfg.get("version_prefix")
    if prefix is not None:
        patch_number = run_number - cfg["version_base_run"]
        if patch_number <= 0:
            raise RuntimeError("자동 버전 기준보다 빌드 번호가 낮습니다.")
        latest_label = f"v{prefix}.{patch_number}"
        target = cfg["image_repo"] + ":" + latest_label + "-sha-" + sha
        tag = current.rsplit(":", 1)[-1]
        match = re.fullmatch(r"(v\d+\.\d+\.\d+)-sha-[0-9a-f]{40}", tag)
        if match:
            current_label = match.group(1)
        elif re.fullmatch(r"sha-[0-9a-f]{40}", tag):
            # Images built before automatic versioning were all v2.0.0.
            current_label = f"v{prefix}.0"
        else:
            current_label = tag[:30]
    else:
        # Unconfigured apps keep their existing SHA-tag behavior.
        target = cfg["image_repo"] + ":sha-" + sha
        current_label = current.rsplit(":", 1)[-1][:30]
        latest_label = "sha-" + sha[:12]
    with LOCK:
        running = bool(task and task["state"] in ("queued", "running"))
        progress = dict(task) if task and task["app_id"] == cfg["id"] else None
    return {"app_id": cfg["id"], "current": current,
            "current_label": current_label, "latest": latest_label,
            "latest_sha": sha, "latest_image": target,
            "available": current != target and not running,
            "ready": True,  # Compatibility with pre-update web UI; no password needed.
            "task": progress,
            "message": "새 빌드가 있습니다." if current != target else "최신 빌드입니다."}


def private_snapshot(cfg, stack, raw, before, after):
    folder = Path(os.getenv("UPDATER_STATE_DIR", "/state"))
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if folder.is_symlink():
        raise RuntimeError("백업 경로가 심볼릭 링크입니다.")
    filename = cfg["id"] + "-" + str(time.time_ns()) + ".json"
    path = folder / filename
    # May contain secrets from Portainer Env. Keep private, never serve via HTTP.
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        json.dump({"stack_id": cfg["stack_id"], "endpoint_id": cfg["endpoint_id"],
                   "compose": raw, "env": stack.get("Env") or [],
                   "before": before, "after": after}, file, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    return filename


def progress(**changes):
    global task
    with LOCK:
        if task is not None:
            task.update(changes)


def worker(cfg, expected_current, target):
    try:
        progress(state="running", phase="작업 상태 확인")
        safety_check(cfg)
        stack, raw, model, before = current_stack(cfg)
        if before != expected_current:
            raise RuntimeError("진행 중 설치 버전이 변경되었습니다.")
        updated = patched_stack(raw, model, cfg["service"], target)
        progress(phase="기존 스택 구성 보관")
        filename = private_snapshot(cfg, stack, raw, before, target)
        progress(phase="이미지 갱신 및 재배포", backup=filename)
        portainer("PUT", "/stacks/" + str(cfg["stack_id"]) + "?endpointId=" + str(cfg["endpoint_id"]),
                 {"StackFileContent": updated, "Env": stack.get("Env") or [],
                  "PullImage": True, "Prune": False})
        progress(phase="배포 스택 확인")
        if current_stack(cfg)[-1] != target:
            raise RuntimeError("배포 후 스택 이미지 불일치")
        progress(state="done", phase="Portainer 이미지 갱신 완료", finished_at=int(time.time()))
    except Exception as exc:
        progress(state="failed", phase=str(exc), finished_at=int(time.time()))


class InstallRequest(BaseModel):
    expected_current: str = Field(min_length=1, max_length=255)
    expected_latest: str = Field(pattern=r"^[0-9a-f]{40}$")


@app.get("/v1/apps/{app_id}")
def get_status(app_id: str, request: Request):
    cfg = authorize(app_id, request)
    try:
        return status(cfg)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/v1/apps/{app_id}/update", status_code=202)
def install(app_id: str, payload: InstallRequest, request: Request):
    global task
    cfg = authorize(app_id, request)
    with LOCK:
        if task and task["state"] in ("queued", "running"):
            raise HTTPException(409, "이미 업데이트가 진행 중입니다.")
    try:
        check = status(cfg)
        if not check["available"] or check["current"] != payload.expected_current or check["latest_sha"] != payload.expected_latest:
            raise HTTPException(409, "최신 정보를 다시 확인하세요.")
        safety_check(cfg)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    with LOCK:
        if task and task["state"] in ("queued", "running"):
            raise HTTPException(409, "이미 업데이트가 진행 중입니다.")
        task = {"app_id": app_id, "state": "queued", "phase": "업데이트 준비",
                "target": check["latest"], "backup": None, "started_at": int(time.time())}
    threading.Thread(target=worker, args=(cfg, payload.expected_current, check["latest_image"]), daemon=True).start()
    return {"accepted": True, "target": check["latest"]}
