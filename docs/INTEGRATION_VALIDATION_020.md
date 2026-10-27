# #020 최종 Linux 통합 검증 — 배포 중단

검증일: 2026-10-26~27 (Asia/Seoul). 기준 커밋 `3df71a5` (#019).
수정 코드/테스트 로컬 커밋: `5be33ce67ae4001552f6771358865c7d8be2daaf`.

**Linux 최종 회귀는 통과했지만 NAS 최종 배포는 수행하지 않았다.**
운영 데이터 보존 해시 확인 중 SSH 계정의 기존 백업 폴더 읽기 권한 거부가 발생했다.
AGENTS의 권한 문제 시 중단 규칙에 따라 멈췄고, 기존 컨테이너 기본 권한을 이용한 읽기 전용
검사 대안을 제시했으나 사용자가 “배포 중단하고 검증 결과만 정리”를 선택했다.
BuildOnly/운영 소스 전송/운영 이미지 빌드/서비스 재생성은 실행하지 않았다. GitHub push 없음.

## 1. 기존 기록 검토

AGENTS.md, README.md의 관련 부분, STORAGE_REFACTOR_PLAN.md의 #013~#018,
SAVE_COMPLETION_019.md, CURRENT_NAS.md, V1_REGISTRATION_STATUS.md 및 관련 테스트를 확인했다.
과거 문서의 이미지 ID와 고정 테스트 개수를 현재 실측으로 사용하지 않았다.

| 항목 | #020 확인 결과 |
| --- | --- |
| #016 자동 rename | NAS 저장 경로의 무저널 자동 이동을 기존 rename 저널로 통합. 실제 Linux에서 no-replace/충돌 보존/전진 복구 통과 |
| #017 alias/sidecar | 기존 정상 alias 재사용, 경쟁 충돌 보존, sidecar/LRC 정체 검사와 구 저널 호환 통과 |
| #018 경로 영속화 | 완료/미완료 저널과 작업 JSON 연결, 재시작, 모호한 경로 차단, LRC 경로 복구 통과 |
| #019 저장 완료 보고 | 음악 게시 뒤 후속 오류는 partial, 실제 쓰기/이동 실패는 failed. 작업 상태 복원 및 최초 원본 정확 복원 통과 |
| #016 Windows의 오류/skip | Linux 읽기 전용 마운트, statvfs, symlink, 실제 디렉터리 fsync 및 renameat2 경로를 건너뜀 없이 검사 |
| #019 P2 옵션 기대값 실패 | 기존 test 기대값에서 use_fingerprint=False 누락. 기존 기능을 바꾸지 않고 기대값 보정 |
| 과거 음악 교체 뒤 HTTP failed/partial 예상 실패 | #019에서 정상 회귀로 전환된 상태를 Linux에서도 확인 |
| 유일한 잔여 예상 실패 | upstream tags.rename_file 직접 호출의 무저널 sidecar rollback 이중 실패. 현재 NAS 저장 API의 호출 경로가 아니며 자동 추측 복구하지 않음 |

예상 실패는 준비/주입 오류가 아니라 마지막
`application recovery left the sidecar detached from existing music` assertion임을
최종 실행기의 traceback 검사로 확인했다. 해당 fixture의 최초 중앙 원본은 보존되며,
명시적인 fixture sidecar 재연결 뒤 정확 복원도 검사한다. 앱의 자동 복구 성공으로 계산하지 않는다.

## 2. Linux 환경과 결과

- 기존 NAS Docker, Python 3.11 환경 이미지
  `sha256:fec14793b0533bb4bbaf2ca4eb5fdf46c1051e377f369adcf0e6b96753f8d90f` 사용.
- 소스: `/tmp/music-tag-020-3df71a5/source`를 `/workspace:ro`로 연결.
  storage/rename_service의 import가 `/workspace/app/`임을 실행 결과에 기록했다.
- `--network none --read-only --tmpfs /tmp:rw,size=512m`, 공개 포트 없음.
  운영 음악 및 운영 data 마운트 없음. 음악 4형식은 ffmpeg로 임시 생성했다.
- 최초 실행은 컨테이너 tmpfs. 최종 실행은 별도 생성한
  `/volume3/docker3/music-tag-validation-020-3df71a5` → `/validation:rw`,
  `TMPDIR=/validation`. NAS 디스크 Btrfs에서 생성 음원/임시 데이터만 처리했다.
- fsync/sync_dir/renameat2 Windows 호환 stub 없이 실제 Linux syscall을 사용했다.
  각 테스트의 지정된 오류 경계만 실패 주입했다.

| 실행 | 실행 수 | 통과 | 일반 실패 | 오류 | skip | 예상 실패 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 최초 전체 (수정 전, tmpfs) | 268 | 265 | 2 | 1 | 0 | 1 |
| 디스크 전체 (새 SIGKILL fixture 경로 보정 전) | 275 | 271 | 3 | 0 | 0 | 1 |
| P18 경로 보정 후 재검사 | 7 | 7 | 0 | 0 | 0 | 0 |
| **최종 디스크 전체** | **275** | **274** | **0** | **0** | **0** | **1** |

최초 표의 setUpClass 오류는 실행 메서드 수와 별도 집계하므로
268 = 통과265 + 실패2 + 예상 실패1이다. 오류는 test_scan_cancel에서 P2Tests를 직접 import해
unittest discovery가 이미 실행한 클래스를 다시 로드한 데서 발생했다. 모듈 import로 최소 수정했다.
일반 실패 2건은 P2 옵션 기본값과 P5의 음악 저장 후 LRC 실패 기대값이었다.
P5는 #019의 partial/music_saved/recovery_pending/warning을 검사하도록 갱신했고,
실제 태그 변경·LRC 전진 복구 검사는 유지했다.

두 번째 전체의 실패 3건은 새 프로세스가 DATA_ROOT/backups를 사용하지만 fixture는
별도 backups를 사용한 테스트 설정 오류였다. 실제 종료 경계에 도달하지 못했으므로
강제 종료 검증 통과로 취급하지 않았다. fixture를 실제 앱 규칙에 맞춘 뒤 7개와 전체를 재실행했다.
최종 unexpected success는 0이다. 중간 실행 수를 최종 수에 합산하지 않는다.

최종 명령 (원문 결과 출력기는 `/tmp/music-tag-020-3df71a5/verify020.py`):

```sh
docker run --rm --name music-tag-020-tests --network none --read-only \
  --tmpfs /tmp:rw,size=512m -e TMPDIR=/validation \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/workspace:/workspace/tests \
  --mount type=bind,source=/tmp/music-tag-020-3df71a5/source,target=/workspace,readonly \
  --mount type=bind,source=/tmp/music-tag-020-3df71a5/verify020.py,target=/verify020.py,readonly \
  --mount type=bind,source=/volume3/docker3/music-tag-validation-020-3df71a5,target=/validation \
  -w /workspace \
  sha256:fec14793b0533bb4bbaf2ca4eb5fdf46c1051e377f369adcf0e6b96753f8d90f \
  python -B /verify020.py
```

실행기는 `unittest.defaultTestLoader.discover('tests', pattern='test*.py')`를 실행하고
결과 수, import 경로, 예상 실패 원문과 마지막 assertion을 확인한다. 앱 함수를 patch하지 않는다.
최종 로그: NAS `/tmp/music-tag-020-3df71a5/linux-final.log`.
로컬 로그는 사용자 작업 공간의 `linux020-final.log`, `windows020.log`에만 보관하며 Git에는 넣지 않는다.
최초 HEAD source-only tar SHA256은
`34e409ccf4a5c3db2a0681033b452ebcb1d170d9829c321be550c2e162c33f5b`로 전송 전후 일치했다.
수정 파일을 격리 소스에만 다시 전송했고 최종 로컬/NAS 파일 해시도 대조했다:

- `app/storage.py`: `6bffd1828cf021cfa485448ae5f4d5a2fa0acfdcdd9fbd1de85e18a7a0cb68a8`
- `tests/test_p18_linux_integration.py`: `a2c487b272870c14c2bdc27f6232a76610edcd1b11aede5c7fdc6a91e654aff8`

## 3. 최소 수정 및 새 보호 검사

운영 수정은 storage.py에만 한정했다. 새 모듈/의존성/DB/기능/저널 형식 변경 없음.
최초 백업 파일들의 fsync만으로 디렉터리 항목의 내구성이 보장되지 않는 공백을 보완했다.
기존 rename_service.sync_dir를 재사용해 create-only hard link, 원자 교체, 백업 디렉터리 공개,
음악 교체 뒤 부모 디렉터리를 동기화한다. 백업의 내부 디렉터리와 상위 연결도 동기화한다.
검증된 기존 백업/sidecar 또는 공개 중 실패한 중앙 백업을 재사용할 때도 sync를 재시도하며,
실패하면 음악 쓰기 전에 차단한다. 음악 교체 뒤 sync 실패는 검증된 게시 바이트를 근거로 partial로 보고한다.

P18 7개는 다음을 확인한다.

- 최초/기존 백업 디렉터리 sync 실패와 재시도에서 음악 미변경, 복구 후 정확 복원.
- 음악 교체 뒤 디렉터리 sync 실패의 partial/music_saved 및 정확 복원.
- 실제 hard link create-only와 renameat2 no-replace 충돌 시 기존 대상 바이트 보존.
- 음악 이동 직후, sidecar 이동 직후, 태그 게시 뒤 LRC 완료 전의 실제 SIGKILL 3개.
  새 Python 프로세스로 작업 JSON을 로드해 복구하며, 음악 재기록을 금지하는 검사와
  반복 복구의 재이동 금지 검사를 적용한다. 음악 bytes/inode/mtime 유지,
  작업 JSON의 현재 경로/LRC/저장 상태 복구, 최초 원본 전체 바이트 복원을 확인한다.

SIGKILL 검사는 프로세스 종료 검증이다. 실제 정전·디스크 캐시 장애·Btrfs 손상 시험을 수행한 것은 아니다.

## 4. Windows·UI·배포 스크립트 검사

| 구분 | 결과 |
| --- | --- |
| Windows Python 보조 suite | 137 실행, 통과128, skip8, 예상 실패1, 일반 실패/오류0 |
| Node UI | test_ui_save.js, test_p2_ui.js, test_command007_ui.js 모두 통과 |
| Node 저장소 | test_gitignore.js, test_repository_readiness.js 통과 |
| PowerShell | tests/deploy-nas.tests.ps1 통과 |
| 수정 파일 diff --check / staged diff --check | 통과 |
| 기존 deploy-nas.ps1 -PreflightOnly | 최초 단계에서 NAS 읽기 전용 보존 검사 통과 |

Windows suite는 P0/P13/P14/P15/P16/P17/P5/P18이다. #019 임시 하네스를 사용해
파일 fsync/디렉터리 sync, no_replace, pathconf, statvfs를 Windows 계약 검사에 맞춰 대체했다.
skip8은 실제 readonly 마운트 1개와 Linux 전용 P18 7개다. 실제 Linux syscall 결과로 계산하지 않는다.
Windows 전체 Python 회귀 또는 P2 symlink 재검사를 수행했다고 주장하지 않는다.

기존 사용자 AGENTS.md에 trailing whitespace/EOF 공백 변경이 있어 배포 스크립트 기본 diff 검사가 막혔다.
해당 파일은 수정하지 않았으며 최초 사전 검사에만 프로세스 범위 Git 설정
`core.whitespace=-blank-at-eol,-blank-at-eof`를 적용했다. 실제 수정 파일은 기본 diff --check로 별도 통과했다.
기존 AGENTS 및 Aider 기록은 수정/커밋하지 않았다.
UI 소스 변경 없음. 최종 배포 후 실제 브라우저 기능 검증은 배포 중단으로 미수행이다.

## 5. NAS 상태, 보존 확인 범위 및 복귀 경로

최종 실측:

- 컨테이너/이미지 태그: `music-tag-filler`, `music-tag-filler-nas:v2.0.0`.
- 실행 이미지: `sha256:fec14793b0533bb4bbaf2ca4eb5fdf46c1051e377f369adcf0e6b96753f8d90f`.
  #020 후보 이미지가 아니며 기존 배포본이다.
- running, 재시작0, StartedAt=`2026-10-25T16:07:31.799981702Z`로 기존 실행 유지.
- 웹/폴더/설정/작업 조회/진단/백그라운드 작업 API 정상 응답.
  작업 요약4건, job_store_error=null, 백그라운드 작업은 빈 배열.
  마지막 컨테이너 로그8행은 조회 API HTTP 200이며 전체 이력 무오류를 보장하지 않는다.
- 운영 mount는 기존 `/volume1/Multimedia/Music`→`/music:rw`,
  `/volume3/docker3/music-tag-filler-v6/data`→`/data:rw`로 확인했다.
  스택/컨테이너 이름, 포트, 정의, 설정, 볼륨을 바꾸지 않았다.
- 기존 이미지에 `music-tag-filler-nas:rollback-020-20261027` 태그를 추가하고 같은 이미지 ID임을 확인했다.
  실제 롤백/재시작 시험은 하지 않았다. 새 배포를 재개한다면 기존 스크립트의 소스/정의 백업과
  변경 서비스 단독 재생성 절차를 따르고, pending 저널이 있는 데이터에 옛 코드를 무조건 적용하지 않는다.
- 운영 inspect/다른 컨테이너 목록은 NAS `/tmp/music-tag-020-3df71a5/`의 준비 기록에만 저장했다.
  전체 운영 data 해시 목록은 SSH 계정의 backups 하위 폴더 읽기 권한 거부로 불완전하다.
  부분 목록을 보존 성공 근거로 사용하지 않았고 컨테이너 권한 우회나 chmod/sudo도 실행하지 않았다.

운영 음악 태그 저장·파일명 변경·복원·전체 스캔, 설정 저장, data 복원/삭제는 실행하지 않았다.
운영 데이터에 직접 쓰지 않았으나 전체 전후 해시 비교는 미완료이므로 완전한 바이트 동일성 검증을 주장하지 않는다.

## 6. 남은 위험 및 재개 조건

- 레거시 무저널 sidecar 분리 잔재는 안전한 수동 확인이 필요하다. 자동 추측 이동/삭제하지 않는다.
- 구 저널은 sidecar/LRC inode 정체 필드 없이 hash만 검증한다. 모호한 연결·외부 교체는 차단한다.
  외부 SMB 프로그램의 동시 쓰기 전체 및 casefold/NFC 이름 경쟁의 원자성을 보장하지 않는다.
- 일반 태그 단독 저장 직후 rename/LRC 저널 없이 종료되면 저장 완료를 추정하지 않으며 재스캔이 필요할 수 있다.
- 실제 정전/하드웨어 장애, 운영 음악이 있는 별도 볼륨의 장애 시험, ACL/xattr/SMB 동시쓰기,
  재해 복구는 미검증이다. 기존 의존성 보안 공지 상태도 변경하지 않았다.
- 후보 이미지 빌드 및 그 이미지 자체의 회귀, 운영 데이터 보존 확인, 최종 배포와 실제 UI 기능 확인이 남았다.
  Linux 통과를 배포 성공으로 표현하지 않는다. 배포를 재개하려면 사용자의 새 배포 요청이 필요하다.
