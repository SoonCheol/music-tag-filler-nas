# Repository Guidelines

## 인계와 활성 구조

작업 전 README.md와 docs/CURRENT_NAS.md를 읽는다. 설치는 docs/INSTALL_KO.md,
업데이트는 docs/OPERATIONS_KO.md, 데이터 복구는 docs/BACKUP_RESTORE_KO.md를 따른다.
활성 코드는 app/main.py, storage.py, search_service.py, job_service.py, preferences.py,
static/index.html과 upstream/이다. *_1·*_new·README_1.md는 보존된 대안이며 실행 대상이 아니다.

## 개발 규칙

기존 v6 UI와 정상 기능을 보존하고 요청한 부분만 변경한다. Python 4칸 들여쓰기,
snake_case와 기존 JavaScript camelCase·DOM ID를 유지한다. P0의 선택 범위·후보/리비전 검사,
최초 원본 보존·무결성 검증·실제 바이트 복원·부분 실패 보고를 우회하지 않는다.
새 모듈/빌드 입력은 배포 허용 목록·Docker context·복구 문서에 반영한다.
의존성 변경은 requirements.txt와 requirements.lock.txt를 함께 검증한다.

## 개발·검증 및 Codex 사용량 관리

요청한 기능과 관련된 코드만 조사·수정한다. 이미 확인한 구조를 매번 처음부터 재분석하지 않는다.
작업 중 불필요한 장문 보고, 전체 로그 출력, 중복 검색·테스트를 피하고 결과를 간결하게 보고한다.
단, 오류 원인 확인과 파일 보호에 필요한 검사·로그는 생략하지 않는다.

### 일반 수정 — 빠른 검증

먼저 git status로 기존 수정 사항을 확인하고, 수정 뒤 git diff 및 git diff --check를 확인한다.
변경 영향 범위에 맞는 테스트만 실행한다. 기존에 통과한 무관한 테스트는 반복하지 않는다.
관련 테스트가 없으면 최소한의 문법·기능 확인을 수행하고 미검증 범위를 보고한다.
변경 내용과 직접 관련된 안전 검사(경로·후보·리비전·백업·복원·권한)는 생략하지 않는다.
테스트 실패를 무시하거나 검증하지 않은 결과를 정상으로 보고하지 않는다.

### UI 수정 — 실제 화면 확인 필수

UI 변경 시 관련 검사 후, 배포를 요청받은 경우 NAS에 배포해 실제 웹 화면에서 변경 동작을 확인한다.
미리보기·옵션·선택 범위·버튼 등 변경한 동작을 실제 UI에서 확인하고, 화면 확인을 코드 검사로 대체하지 않는다.
실제 음악 저장·복원·전체 스캔을 UI 확인용으로 실행하지 않는다.
NAS 접속·배포·화면 확인이 불가능하면 성공으로 간주하지 말고 사유를 보고한다.

### GitHub Push 전 — 종합 검증

전체 회귀 검증은 GitHub Push 또는 릴리스 준비 시 집중 실행한다.
Node: tests/test_ui_save.js, tests/test_p2_ui.js, tests/test_gitignore.js, tests/test_repository_readiness.js.
PowerShell: tests/deploy-nas.tests.ps1 (프로세스 범위 ExecutionPolicy Bypass).
Linux Docker: unittest discover -s tests -p 'test_p*.py'.
전체 검증 결과·실패·미실행 항목을 보고하고, 실패가 있으면 사용자 확인 없이 Push하지 않는다.
단, 배포·저장·복원 등 고위험 변경은 Push 전이라도 필요한 범위까지 검증한다.

### 테스트 데이터·기록

운영 음악/data는 절대 테스트에 마운트하지 않고 /tmp 생성 음원만 사용한다.
테스트 개수는 실제 실행 결과를 기준으로 보고한다. 기존 문서의 고정 개수를 최신 수치로 가정하지 않는다.
CI는 검증만 하며 NAS에 접속하지 않는다.

## NAS 배포와 복구

정식 이름 이전 작업은 docs/V1_REGISTRATION_STATUS.md를 먼저 확인한다.
현재 고정 스택·컨테이너·서비스 이름은 music-tag-filler, 이미지는 music-tag-filler-nas:v1.0.0이다.
2026-10-21 Portainer 공식 API로 이전 완료했다. 스택 ID 32와 관리자 전용 접근 제어를 보존했다.
이후에는 고정 이름을 유지하고 이미지 버전 태그만 갱신한다. NAS 호스트 경로는 바꾸지 않는다.

배포 요청 시 변경 영향에 맞는 필수 검증 후 기존 deploy-nas.ps1을 사용한다. 기본은 변경 파일 백업/SCP·빌드·해당 서비스 단독 재생성이다.
-CheckOnly는 로컬, -PreflightOnly는 NAS 읽기 전용 검사, -BuildOnly는 전송/빌드까지다.
로컬 JSON의 기존 키와 legacy SCP 방식을 유지한다. Portainer 원본을 저장소 YAML로 덮어쓰지 않는다.
Docker 환경·포트·볼륨과 승인된 /music:rw를 보존한다. 테스트는 운영 음악을 수정하지 않는다.
2026-10-21 사용자 요청으로 음악만 rw로 전환했다. MusicReadOnly=false를 유지하고 모드 불일치 시 중단한다.
sudo/인증/권한 문제면 중단하고 보고하며 권한 확대·호스트키 우회는 하지 않는다.
data 복원·운영 중지·실제 백업은 별도 사용자 요청이 있을 때만 수행한다.

## GitHub·비밀값·이력

비공개 저장소 SoonCheol/music-tag-filler-nas를 대상으로 한다. commit/push/tag/remote 변경은
사용자가 요청한 범위에서만 한다. 일반 수정은 사용자 승인된 개발 흐름에 따라 검증 후 로컬 commit하며,
push/tag/remote 변경은 별도 명시 요청이 있을 때만 한다. git init·강제 push·amend·기록 재작성·기존 변경 폐기는 금지한다.
명시적으로 검토한 파일만 stage하며 git add -f를 쓰지 않는다.
개인키·비밀번호·실제 API 키·data·음악·백업 원본·로그를 commit하지 않는다.
운영 IP·계정·폴더·키 위치라는 비밀값 아닌 메타데이터는 사용자의 명시 요청으로
docs/CURRENT_NAS.md와 현재 YAML에 보관한다. 이를 비밀 누출로 오인해 삭제하지 말고 저장소 비공개를 유지한다.
deploy-nas.local.json은 여전히 제외한다. .gitignore는 내용 검사나 과거 기록 삭제를 대신하지 않는다.
### 변경 이력 관리

기능 추가·개선·버그 수정 후 GitHub에 push할 때마다, push 전에 CHANGELOG.md를 함께 갱신하고 커밋한다.
Git 커밋 날짜 기준으로 날짜별 추가 기능·기능 개선·버그 수정을 한글로 구분하고,
코드 수정 목록 대신 사용자가 체감하는 동작과 달라진 점을 설명한다.
근거 커밋을 남기며, 기록에서 확인할 수 없는 기능·날짜·배포·검증 결과를 추측하지 않는다.
같은 날짜의 중복 항목은 최종 동작 중심으로 정리하고, 기능 변경이 없는 문서 정리에는 기능을 꾸며 추가하지 않는다.
릴리스에는 CHANGELOG와 테스트·배포한 커밋/이미지 ID를 기록한다.
원본 MIT 고지와 licenses/를 보존하고, 추가 코드 전체의 라이선스를 임의로 선언하지 않는다.
