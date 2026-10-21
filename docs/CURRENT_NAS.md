# 현재 NAS 구성 — 비공개 저장소용 운영 기록

2026-10-21에 실제 NAS를 읽기 전용 조사했다. 사용자의 이번 지시에 따라
주소·계정·경로는 정확히 기록한다. 이 문서는 Git 업로드 대상이므로 저장소를
비공개로 유지한다. 비밀번호·개인키 내용·실제 API 키는 기록하지 않는다.

| 항목 | 확인한 값 |
| --- | --- |
| GitHub 백업 대상 | `https://github.com/SoonCheol/music-tag-filler-nas` |
| Windows 작업 폴더 | `C:\Codex\music-tag-filler-nas` |
| NAS / SSH | `hitmyhead@192.168.0.100` |
| 기존 SSH 개인키 위치 | `C:\Users\homes\.ssh\codex_nas` (파일 자체는 Git 보관 금지) |
| NAS 프로젝트 | `/volume3/docker3/music-tag-filler-v6` |
| 음악 원본 | `/volume1/Multimedia/Music` → `/music:rw` |
| 프로그램 데이터 | `/volume3/docker3/music-tag-filler-v6/data` → `/data:rw` |
| 이미지 | `music-tag-filler-nas:v6` |
| 컨테이너·Compose 프로젝트·서비스 | 모두 `music-tag-filler-v6` |
| 웹 | `http://192.168.0.100:8000/` |
| 포트 | 호스트 `8000` → 컨테이너 `8000/tcp` |
| Portainer 컨테이너 | `portainer` |
| 현재 Portainer 정의 위치 | 컨테이너 내부 `/data/compose/32/docker-compose.yml` |
| 기본 네트워크 | `music-tag-filler-v6_default` |
| 재시작 정책 | `unless-stopped` |
| Docker / Compose | `29.6.2` / `v5.1.3` |
| NAS CPU | `x86_64` (ARM 이식은 별도 검증 필요) |
| 컨테이너 작업 디렉터리 | `/app` |
| 실행 사용자 | 이미지 기본 사용자 (현재 명시적 `user` 없음) |
| 사용자 환경변수 | `MUSIC_ROOT=/music`, `DATA_ROOT=/data`, `TZ=Asia/Seoul` |
| 제한/권한 | 별도 CPU·메모리 제한 없음, privileged 아님, rootfs 읽기 전용 아님 |
| 서버 실행 | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1` |
| 실행 중 이미지 ID | `sha256:467fd3b7a2c2f254aff3f2b316ae4eda46e9dc725683a377e2408863d6f00ca0` |

조사 시 `data/` 최상위에는 `jobs.json`, `backups/`가 있었다.
`settings.json`, `acoustid_key.txt`는 없었다. 설정 파일이 없으면 코드 기본값을 사용한다.
AcoustID 키 미설정, fpcalc 사용 가능이라는 기존 진단 결과와 일치한다.
설정/API 키의 **내용**이나 음악 파일은 이번 조사에서 읽지 않았다.

## 로컬 배포 설정 복원

실제 값은 Git에서 제외되는 `deploy-nas.local.json`에 보관한다.
PC 교체 시 `deploy-nas.example.json`을 복사하고 아래 비밀값 없는 정보를 입력한다.
SSH 키 파일은 별도 안전한 백업에서 가져오거나 새 키를 등록한다.

```json
{
  "NasTarget": "hitmyhead@192.168.0.100",
  "SshKey": "C:\\Users\\homes\\.ssh\\codex_nas",
  "RemoteRoot": "/volume3/docker3/music-tag-filler-v6",
  "Image": "music-tag-filler-nas:v6",
  "Container": "music-tag-filler-v6",
  "PortainerStackFile": "/data/compose/32/docker-compose.yml",
  "WebBaseUrl": "http://192.168.0.100:8000",
  "MusicReadOnly": false
}
```

새 PC 사용자명이 다르면 `SshKey`만 새 절대 경로로 바꾼다. 새 NAS로 이사하면
주소·계정·프로젝트/음악/data 경로와 두 YAML을 새 환경에 맞춘다.
Portainer 스택 ID `32`는 영구 식별자가 아니다. 새 스택을 만든 뒤 실제 정의 위치를
Portainer에서 확인하여 로컬 JSON에 반영한다. 추측한 ID로 기존 스택을 덮어쓰지 않는다.

## 현재 기록과 소스의 차이

위 이미지 ID는 이미 배포된 UI 수정 버전이다. 이번 장기 보관 준비에서 만든
의존성 잠금·문서·YAML·CI·배포 허용 목록 변경은 아직 운영 NAS에 배포하지 않았다.
컨테이너 이미지와 현재 작업 트리의 Git 커밋이 같다고 가정하지 않는다.
현재 GitHub push도 아직 수행하지 않았다.

사용 한도 중단 후 마지막 SSH 재확인에서는 22번 포트 연결이 거부되었다.
위 표는 앞서 성공한 읽기 전용 조사의 스냅샷이며, 재개 시점의 가동 상태를
새로 확인한 기록은 아니다. 접속 복구 전에는 이를 근거로 자동 변경을 수행하지 않는다.

### 이후 재확인: 2026-10-21 13:19 KST

기존 키로 SSH 연결이 다시 정상화되었고 운영 컨테이너 running·재시작 횟수 0,
동일 이미지 ID·마운트·환경·포트를 확인했다. 웹 HTTP 200과 운영/로컬 HTML 일치,
활성 앱 파일 17개 SHA256 일치, diagnostics 오류 없음, 폴더 3517개도 확인했다.
키는 여전히 미설정이며 fpcalc는 사용 가능하다. 앞선 연결 거부는 과거 점검 결과다.
컨테이너/음악/설정은 변경하지 않았다. [v1.0.0 준비 기록](RELEASE_V1_0_0.md)을 참고한다.

## 음악 쓰기 모드 변경 — 2026-10-21

사용자 요청 및 격리된 NAS 음원 검증 후 현재 운영 음악 마운트는 `/music:rw`이다.
로컬 배포 설정의 `MusicReadOnly`는 JSON boolean `false`로 맞춘다. 문자열은 허용하지 않는다.
항목이 없는 이전 설정은 true로 처리되며 실제 모드가 다르면 배포를 중단한다.
배포는 마운트 모드를 자동 변경하지 않고 현재 승인된 설정만 보존한다.
기존 문서의 ro 설명은 전환 이전 기록이며 [전환 검증](RW_MOUNT_VALIDATION.md)을 따른다.
