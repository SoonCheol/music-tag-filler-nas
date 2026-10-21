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

## 테스트

먼저 git status와 기존 수정 사항을 확인하고, 수정 뒤 git diff 및 git diff --check를 확인한다.
Node로 tests/test_ui_save.js, test_p2_ui.js, test_gitignore.js, test_repository_readiness.js를 실행한다.
PowerShell은 tests/deploy-nas.tests.ps1을 프로세스 범위 ExecutionPolicy Bypass로 실행한다.
Linux Docker 이미지에서 unittest discover -s tests -p 'test_p*.py'를 실행한다.
운영 음악/data는 절대 테스트에 마운트하지 않고 /tmp 생성 음원만 사용한다.
현재 기준 Python 55개이며 테스트 추가 후 실제 수를 기록한다. CI는 검증만 하며 NAS에 접속하지 않는다.

## NAS 배포와 복구

정식 이름 이전 작업은 docs/V1_REGISTRATION_STATUS.md를 먼저 확인한다.
현재 고정 스택·컨테이너·서비스 이름은 music-tag-filler, 이미지는 music-tag-filler-nas:v1.0.0이다.
2026-10-21 Portainer 공식 API로 이전 완료했다. 스택 ID 32와 관리자 전용 접근 제어를 보존했다.
이후에는 고정 이름을 유지하고 이미지 버전 태그만 갱신한다. NAS 호스트 경로는 바꾸지 않는다.

배포 요청 시 테스트 후 기존 deploy-nas.ps1을 사용한다. 기본은 변경 파일 백업/SCP·빌드·해당 서비스 단독 재생성이다.
-CheckOnly는 로컬, -PreflightOnly는 NAS 읽기 전용 검사, -BuildOnly는 전송/빌드까지다.
로컬 JSON의 기존 키와 legacy SCP 방식을 유지한다. Portainer 원본을 저장소 YAML로 덮어쓰지 않는다.
Docker 환경·포트·볼륨과 승인된 /music:rw를 보존한다. 테스트는 운영 음악을 수정하지 않는다.
2026-10-21 사용자 요청으로 음악만 rw로 전환했다. MusicReadOnly=false를 유지하고 모드 불일치 시 중단한다.
sudo/인증/권한 문제면 중단하고 보고하며 권한 확대·호스트키 우회는 하지 않는다.
data 복원·운영 중지·실제 백업은 별도 사용자 요청이 있을 때만 수행한다.

## GitHub·비밀값·이력

비공개 저장소 SoonCheol/music-tag-filler-nas를 대상으로 한다. commit/push/tag/remote 변경은
사용자가 요청한 범위에서만 한다. git init·강제 push·amend·기록 재작성·기존 변경 폐기는 금지한다.
명시적으로 검토한 파일만 stage하며 git add -f를 쓰지 않는다.
개인키·비밀번호·실제 API 키·data·음악·백업 원본·로그를 commit하지 않는다.
운영 IP·계정·폴더·키 위치라는 비밀값 아닌 메타데이터는 사용자의 명시 요청으로
docs/CURRENT_NAS.md와 현재 YAML에 보관한다. 이를 비밀 누출로 오인해 삭제하지 말고 저장소 비공개를 유지한다.
deploy-nas.local.json은 여전히 제외한다. .gitignore는 내용 검사나 과거 기록 삭제를 대신하지 않는다.
릴리스에는 CHANGELOG와 테스트·배포한 커밋/이미지 ID를 기록한다.
원본 MIT 고지와 licenses/를 보존하고, 추가 코드 전체의 라이선스를 임의로 선언하지 않는다.
