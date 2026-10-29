# Repository Guidelines

## 인계와 활성 구조

작업 시작 시 README.md와 docs/CURRENT\_NAS.md는 현재 요청과 관련된 부분만 확인한다.

동일 세션에서 이미 확인했고 변경되지 않았다면 다시 읽지 않는다.

필요한 설정이나 구조가 불확실할 때만 추가 확인한다.

설치는 docs/INSTALL\_KO.md,
업데이트는 docs/OPERATIONS\_KO.md,

데이터 복구는 docs/BACKUP\_RESTORE\_KO.md를 따른다.
활성 코드는 app/main.py, storage.py, search\_service.py, job\_service.py, preferences.py,
static/index.html과 upstream/이다. #032에서 제거한 구버전·중복 파일 9개는 Git 이력에서 복구하며 실행 대상이 아니다.

## 개발 규칙

기존 v6 UI와 정상 기능을 보존하고 요청한 부분만 변경한다. Python 4칸 들여쓰기,
snake\_case와 기존 JavaScript camelCase·DOM ID를 유지한다. P0의 선택 범위·후보/리비전 검사,
최초 원본 보존·무결성 검증·실제 바이트 복원·부분 실패 보고를 우회하지 않는다.
새 모듈/빌드 입력은 배포 허용 목록·Docker context·복구 문서에 반영한다.
의존성 변경은 requirements.txt와 requirements.lock.txt를 함께 검증한다.

## 파일 생성 위치와 임시 파일 관리

앞으로 모든 작업에서 프로젝트 폴더에는 실제 필요한 소스코드·설정·문서만 저장한다.
임시 분석 파일·실행 로그·테스트 산출물·일회성 스크립트는 시스템 임시 폴더(`$env:TEMP`)에 저장하며,
가능하면 작업별 하위 폴더를 사용한다. OneDrive의 문서 폴더에는 임시 파일을 생성하지 않는다.
프로젝트 루트에 `*_1`, `*_new`, `*_backup` 등의 중복 파일을 임의로 생성하지 않는다.

기존 소스와 문서는 가능한 한 해당 파일을 직접 수정한다.
기존 `scratch` 자료는 삭제하거나 이동하지 않는다. 기존 작업 JSON·음악 파일·캐시·백업·롤백 자료도 삭제하지 않는다.
사용자 승인 없이 기존 파일을 대량 정리하거나 이동하지 않는다.

작업 완료 후에는 이번 작업에서 생성한 임시 파일만 안전하게 정리한다.
기존에 있던 파일은 자동 삭제하지 않는다.

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
Node: tests/test\_ui\_save.js, tests/test\_p2\_ui.js, tests/test\_gitignore.js, tests/test\_repository\_readiness.js.
PowerShell: tests/deploy-nas.tests.ps1 (프로세스 범위 ExecutionPolicy Bypass).
Linux Docker: unittest discover -s tests -p 'test\_p\*.py'.
전체 검증 결과·실패·미실행 항목을 보고하고, 실패가 있으면 사용자 확인 없이 Push하지 않는다.
단, 배포·저장·복원 등 고위험 변경은 Push 전이라도 필요한 범위까지 검증한다.

### 테스트 데이터·기록

운영 음악/data는 절대 테스트에 마운트하지 않고 /tmp 생성 음원만 사용한다.
테스트 개수는 실제 실행 결과를 기준으로 보고한다. 기존 문서의 고정 개수를 최신 수치로 가정하지 않는다.
CI는 검증만 하며 NAS에 접속하지 않는다.

## NAS 배포와 복구

정식 이름 이전 작업은 docs/V1\_REGISTRATION\_STATUS.md를 먼저 확인한다.
현재 고정 스택·컨테이너·서비스 이름은 music-tag-filler, 이미지는 music-tag-filler-nas:v2.0.0이다.
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
docs/CURRENT\_NAS.md와 현재 YAML에 보관한다. 이를 비밀 누출로 오인해 삭제하지 말고 저장소 비공개를 유지한다.
deploy-nas.local.json은 여전히 제외한다. .gitignore는 내용 검사나 과거 기록 삭제를 대신하지 않는다.

### 변경 이력 관리

기능 추가·개선·버그 수정 후 GitHub에 push할 때마다, push 전에 CHANGELOG.md를 함께 갱신하고 커밋한다.
Git 커밋 날짜 기준으로 날짜별 추가 기능·기능 개선·버그 수정을 한글로 구분하고,
코드 수정 목록 대신 사용자가 체감하는 동작과 달라진 점을 설명한다.
근거 커밋을 남기며, 기록에서 확인할 수 없는 기능·날짜·배포·검증 결과를 추측하지 않는다.
같은 날짜의 중복 항목은 최종 동작 중심으로 정리하고, 기능 변경이 없는 문서 정리에는 기능을 꾸며 추가하지 않는다.
릴리스에는 CHANGELOG와 테스트·배포한 커밋/이미지 ID를 기록한다.
원본 MIT 고지와 licenses/를 보존하고, 추가 코드 전체의 라이선스를 임의로 선언하지 않는다.

## 현재 모듈·상태 경계

README의 주요 폴더 표와 docs/SCAN_SERVICE.md, docs/LYRICS_SERVICE.md,
docs/UI_JAVASCRIPT.md를 작업 범위에 맞게 참고한다. main은 API·공유 jobs·시계·저장 콜백을
소유한다. request_models는 입력 검증, scan_service는 ScanContext로 기존 참조/잠금을 받아
파일 읽기와 최대 3개 검색을 진행한다. main을 역으로 import하거나 공유 상태를 복제하지 않는다.
job_service는 수집·상태·이어하기, job_store는 data/jobs/<id>.json 원자 저장을 담당한다.
기존 jobs.json은 jobs_legacy.json으로 덮어쓰기 없이 보관하며 자동 삭제/가져오기를 하지 않는다.
재시작 시 활성 스캔은 interrupted가 될 수 있다. 저장 작업 진행 목록·가사/커버 캐시·토큰은
메모리 상태이므로 영구 작업 기록/사용자 초안과 혼동하지 않는다. Uvicorn worker는 1을 유지한다.

search_service는 iTunes/MusicBrainz/AcoustID 후보 조합과 커버를 담당하고 upstream/net은
외부 요청 제한·재시도·검색 캐시를 담당한다. lyrics_service는 가사 캐시·Future 병합·토큰을
소유한다. 제공처 호출을 저장 잠금 안으로 옮기거나 캐시 키의 국가·쿼리·리비전 경계를 생략하지 않는다.
검색 모드와 강제 재검색의 의미, 후보 ID·검색 generation 검사와 사용자 선택 보존을 유지한다.

storage의 OPERATION_LOCK·원본 SHA256·최초 바이트 백업·manifest·원자 게시/fsync를 보존한다.
rename_service와 lyric_assets의 복구 저널을 우회하지 않는다. main/storage/관련 모듈과
static/js의 모든 파일은 같은 버전으로 빌드·복원한다. 저장 후 일부 실패를 전체 성공으로 표시하지 않는다.
수동 태그·직접 입력 가사·선택 후보·수동 커버를 늦은 검색 응답으로 덮어쓰지 않는다.
가사 불일치 승인은 명시된 수동 선택에 한정하고 파일/리비전 검증은 계속 적용한다.
빈 가사·빈 커버·체크 해제 항목은 기존 데이터 삭제 명령으로 취급하지 않는다.

## 문서·설치 예시 작업의 최소 검증

문서/예시만 바꾸며 사용자가 대규모 검증을 금지한 경우 해당 제한이 전체 회귀 지침보다 우선한다.
git diff --check, 문서 링크/저장소 준비 검사, gitignore 검사와 가능한 Compose 정적 검증을 수행한다.
기존 기능 변경까지 업로드하더라도 실행하지 않은 회귀·Docker 빌드·화면·NAS 검증은 명시한다.
과거 테스트 통과 기록을 이번 커밋의 통과 결과로 쓰지 않는다.
운영 음악은 테스트 입력·수정·삭제 대상으로 절대 사용하지 않는다. 작업 JSON·캐시·백업도 지우지 않는다.
compose.example.yml은 신규 격리 설치만 위한 예시이며 운영 YAML은 기존 값을 유지한다.
.env.example은 설명용이다. .env 로딩이 자동으로 Python 또는 기존 Compose에 연결된다고 가정하지 않는다.

GitHub 업로드 전 AI 대화 이력·개인 데이터·임시 미리보기·실행 로그도 제외한다.
.gitignore는 추적 중 파일이나 과거 커밋을 숨기지 않으므로 전송할 커밋과 파일 내용도 검사한다.
기존 운영 메타데이터 문서는 역사 기록이며 새 설치 예시에 개인 계정·주소·키 경로를 복사하지 않는다.
롤백은 docs/OPERATIONS_KO.md를 따르며 보존된 이미지/기존 정의와 data 호환성을 확인한다.
배포 스크립트의 rollback-* 태그 보존은 자동 복귀를 뜻하지 않는다. 배포·볼륨 삭제는 별도 요청 없이 실행하지 않는다.
