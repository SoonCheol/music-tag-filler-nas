# 현재 NAS 구성 — 비공개 저장소용 운영 기록

2026-10-21 Portainer 공식 API로 정식 운영 이름 이전을 완료하고 실제 상태를 확인했다.
운영 메타데이터는 사용자 요청으로 보관한다. 저장소는 Private로 유지하며 비밀번호·토큰·개인키 내용은 기록하지 않는다.

| 항목 | 확인한 값 |
| --- | --- |
| GitHub | https://github.com/SoonCheol/music-tag-filler-nas (Private) |
| Windows 프로젝트 | `C:\Codex\music-tag-filler-nas` |
| NAS / SSH | `hitmyhead@192.168.0.100` |
| SSH 개인키 위치 | `C:\Users\homes\.ssh\codex_nas` (파일 업로드 금지) |
| NAS 프로젝트 | `/volume3/docker3/music-tag-filler-v6` (기존 경로 유지) |
| 음악 | `/volume1/Multimedia/Music` → `/music:rw` |
| 프로그램 data | `/volume3/docker3/music-tag-filler-v6/data` → `/data:rw` |
| 스택·Compose 프로젝트·서비스·컨테이너 | 모두 `music-tag-filler` |
| 이미지 | `music-tag-filler-nas:v1.0.0` |
| 이미지 ID | `sha256:148df465bfc0ecbfa3020834d479772e02d08ad8f6ce8877e0a45f79f1ded93b` |
| 웹·포트 | `http://192.168.0.100:8000/`, `8000:8000/tcp` |
| Portainer | `http://192.168.0.100:9001`, 컨테이너 `portainer` |
| 스택 ID / 환경 ID | `32` / `7` |
| 원본 정의 | Portainer 내부 `/data/compose/32/docker-compose.yml` |
| 접근 제어 | ID 44, AdministratorsOnly=true 보존 |
| 기본 네트워크 | `music-tag-filler_default` |
| 환경변수 | `MUSIC_ROOT=/music`, `DATA_ROOT=/data`, `TZ=Asia/Seoul` |
| 재시작 | `unless-stopped` |
| Docker / Compose / CPU | `29.6.2` / `v5.1.3` / `x86_64` |
| 작업 디렉터리·실행 사용자 | `/app`, 이미지 기본 사용자 |
| 명령 | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1` |
| 리소스·권한 | 별도 CPU/메모리 제한 없음, privileged=false, ReadonlyRootfs=false |
| 최종 상태 | Portainer active, 컨테이너 running·재시작 0, 웹 HTTP 200 |

## 로컬 배포 설정

Git에서 제외하는 `deploy-nas.local.json`의 현재 값이다. 새 PC에서는 예시 JSON을 복사하고 채운다.
Portainer 스택 ID는 새 NAS에서 달라질 수 있으므로 실제 경로를 확인한다.

```json
{
  "NasTarget": "hitmyhead@192.168.0.100",
  "SshKey": "C:\\Users\\homes\\.ssh\\codex_nas",
  "RemoteRoot": "/volume3/docker3/music-tag-filler-v6",
  "Image": "music-tag-filler-nas:v1.0.0",
  "Container": "music-tag-filler",
  "PortainerStackFile": "/data/compose/32/docker-compose.yml",
  "WebBaseUrl": "http://192.168.0.100:8000",
  "MusicReadOnly": false
}
```

고정 운영 이름은 이후에도 유지하고 새 버전은 이미지 태그만 변경한다.
버전 전환 시 현재 Portainer 정의의 다른 값을 보존하면서 이미지 태그와 로컬 JSON을 함께 맞춘다.
배포 스크립트는 기존 이미지·정의·마운트 모드 불일치를 자동 우회하지 않는다.

## 인증·백업·보존

사용자가 지정한 Portainer 토큰은 외부 파일 `C:\Users\homes\.codex\portainer-token.txt`에서
메모리로 읽어 `X-API-Key`에만 사용했다. 토큰 내용은 저장소·로그·명령 인자에 넣지 않는다.
일상 배포는 기존 SSH/SCP 방식이며 이 토큰을 배포 JSON에 복사할 필요가 없다.

NAS 프로젝트의 `deploy-backups/name-migration-20261021/`에 원본 Portainer 정의와
컨테이너 inspect, data tar, 변경 전후 컨테이너 목록, 원본/대상 YAML을 보존했다.
전후 data가 일치하며 음악 파일을 수정하지 않았다. 다른 컨테이너 ID도 그대로다.
기본 네트워크 이름은 새 Compose 프로젝트에 맞춰 변경됐다.

새 이미지의 기존 회귀 55개 및 격리된 음원 4종 저장·원본 바이트 복원 검증은
[등록 기록](V1_REGISTRATION_STATUS.md)을 따른다. 이번 이름 이전에서는 이 시험들을 반복하지 않았다.
AcoustID 키 미설정과 기존 보안 공지 제한은 [보안 보고서](SECURITY_AUDIT_KO.md)에 남아 있다.
원본 음악·data·API 키·SSH 개인키는 GitHub만으로 복구할 수 없으며 별도 백업이 필요하다.
