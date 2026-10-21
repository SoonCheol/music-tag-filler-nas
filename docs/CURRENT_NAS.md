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
| 이미지 ID | `sha256:02784b006ca7bff50ce8d151d12dd0f31fce70a6dcad74bf566a6a95075d9061` |
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

## 저장 전 UI 안내 개선 배포 — 2026-10-21

기존 deploy-nas.ps1 및 local JSON으로 UI 변경을 배포했다. 스택/컨테이너 이름과
마운트·환경·포트·권한은 기존 검사를 통과했다. 기존 이미지 태그를 사용해 재빌드했으며
상단 이미지 ID가 이번 실행 이미지다. GitHub v1.0.0 태그/Release와 HEAD dce4018은 변경하지 않았다.
소스는 미커밋 작업본이다. 이전 릴리스 이미지 ID는 V1_REGISTRATION_STATUS.md의 역사적 기록을 따른다.
백업: /volume3/docker3/music-tag-filler-v6/deploy-backups/20261021-061358-dac02e5b.
웹 HTTP 200, 운영 HTML과 로컬 HTML 바이트 일치, 폴더 API 및 실제 브라우저 UI 표시 확인.
관련 UI 테스트만 통과시켰고 전체 회귀는 반복하지 않았다. 운영 음악 저장·복원·스캔, 설정 저장, GitHub push는 실행하지 않았다.

## 모달 및 폴더 복원 개선 배포 — 2026-10-21

기존 deploy-nas.ps1/local JSON으로 배포 완료. 컨테이너 music-tag-filler와 기존 설정/마운트 유지 검증.
원본 백업: /volume3/docker3/music-tag-filler-v6/deploy-backups/20261021-062906-0486bc15.
현재 이미지 ID는 상단 표를 따른다. Git HEAD dce4018 및 GitHub 태그/Release는 그대로이며 미커밋 작업본을 배포했다.
관련 UI 테스트 2종 및 CheckOnly/PreflightOnly 통과, 웹 HTTP 200 및 운영 HTML과 로컬 파일 바이트 일치.
실제 웹에서 편집 취소/계속 편집, 폴더·필터·파일 목록의 새로고침 복원, 전체 스캔 경고 후 취소 확인.
저장 결과 모달은 배포 HTML을 사용하는 로컬 가상 데이터 미리보기와 격리 UI 테스트로 확인했다.
실제 스캔·음악 저장·원본 복원·설정 저장·GitHub push는 실행하지 않았고 서버 작업은 기존 2건을 유지했다.

## 후보 적용 피드백 및 툴팁 배포 — 2026-10-21

기존 배포 스크립트/설정으로 music-tag-filler 단독 재생성. 기존 마운트/환경/포트 유지 및 HTTP/폴더 API 검사 통과.
백업: /volume3/docker3/music-tag-filler-v6/deploy-backups/20261021-064010-6fe6526e.
현재 실행 이미지 ID는 상단 표와 같다. 소스는 기존 HEAD dce4018 위의 미커밋 작업본이며 GitHub push/태그 변경 없음.
UI 테스트 2종 통과. 실제 웹에서 후보 값 반영/필드 강조/중복 적용 사유/파일 저장 전 안내와 6개 툴팁의 키보드 포커스 표시·줄바꿈 확인.
마우스 진입 이벤트 연결은 격리 UI 검사로 확인. 검증 초안은 편집 취소 후 새로고침으로 제거했다.
실제 음악 저장·복원·스캔·옵션 기억은 실행하지 않았고 작업 기록 2건을 유지했다.

## 저장 전 확인 모달 배포 및 로컬 커밋 — 2026-10-21

기존 deploy-nas.ps1 및 local JSON으로 배포 완료. 기존 컨테이너 이름/마운트/환경/포트 유지 검사 통과.
백업: /volume3/docker3/music-tag-filler-v6/deploy-backups/20261021-065027-ea878735. 현재 이미지 ID는 상단 표를 따른다.
HTTP 200 및 운영 HTML과 로컬 소스 바이트 일치. 관련 UI 검사 2종 통과.
실제 운영 페이지에서 현재 곡·필터 결과·작업 전체·체크 항목 저장의 사용자 정의 모달과 기본 JS 확인창 없음 확인.
모든 운영 검증은 취소/Escape로 종료했고 실제 음악 저장·복원·스캔·설정 저장은 실행하지 않았다. 작업 기록 2건 유지.
이 배포와 앞서 이 대화에서 구현한 UI 개선의 소스·관련 테스트·문서를 사용자 요청으로 로컬 Git에 함께 커밋한다.
이전 절의 dce4018/미커밋 설명은 당시 배포 기록이다. 최신 로컬 커밋은 git log를 따른다. GitHub push 및 기존 태그/Release 변경 없음.

## 현재 태그 미리보기 배포 — 2026-10-21

기존 deploy-nas.ps1/local JSON으로 배포 완료. 컨테이너 이름/마운트/환경/포트 유지 검사 통과.
백업: /volume3/docker3/music-tag-filler-v6/deploy-backups/20261021-074607-f078a669. 현재 이미지 ID는 상단 표와 같다.
관련 UI 검사 2종 통과 및 저장/원본 복원 함수와 기존 HEAD의 내용 동일 확인. HTTP 200, 운영 HTML과 로컬 소스 바이트 일치.
실제 웹에서 후보 클릭의 아래 자동 반영, 미리보기 빨간 텍스트/커버 안내, 취소 시 아래 초안 유지 및 체크 해제 반영 확인.
검증 초안은 편집 취소 후 새로고침으로 제거했다. 실제 음악 저장·복원·스캔·옵션 기억은 실행하지 않았다.
정상 확인 후 이 미리보기 변경과 관련 테스트/운영 기록을 로컬 Git에 커밋한다. GitHub push/태그/Release 변경 없음.

## 저장 옵션 및 미리보기 정합성 배포 — 2026-10-21

현재 이미지 ID는 상단 표를 따른다. 기존 deploy-nas.ps1/설정으로 배포 및 마운트/환경/포트 유지 확인.
진행 중 49곡 스캔 완료를 기다린 후 재생성했다. 일시적인 NAS 연결 실패는 복구됐고 작업 강제 중지 없음.
소스 백업: deploy-backups/20261021-075827-4c98ee2f 및 20261021-080526-d151cb58.
UI 검사 2종 및 관련 격리 Python 검사 13개 통과. 전체 회귀 미반복, 이번 테스트 정의 4개 추가(총 59개).
실제 웹의 빈 태그 옵션 전환/후보/직접 수정/체크 반영 확인. HTTP 200 및 로컬 HTML과 일치.
검증 초안 제거, 운영 음악 쓰기/원본 복원/설정 기억/GitHub push 미실행. 상세 옵션별 결과는 OPTIONS_VALIDATION_KO.md.
