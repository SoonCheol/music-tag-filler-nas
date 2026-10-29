# #028 GitHub 인계 — 2026-10-30

## 범위

README·AGENTS와 설치 예시/제외 규칙을 보완했다. 기존 운영 docker-compose.yml,
portainer-stack.yml, Dockerfile, requirements 두 파일은 변경하지 않았다.
새 compose.example.yml은 운영과 분리된 상대 경로/18000 포트를 사용한다.
.env.example은 참고용이며 기존 Compose의 변수 치환을 추가하지 않았다.

작업 시작 시 master는 origin/master보다 27커밋 앞섰으며 앱·UI·테스트·배포 스크립트에
기존 미커밋 변경이 있었다. 사용자가 기존 앱 변경까지 검토 후 함께 업로드하도록 승인했다.
기존 앱 변경을 보존하여 포함하고, 이번 작업에서 앱 기능 코드를 새로 수정하지 않았다.
AI 대화 이력, 임시 미리보기, scratch, 운영 음악/data/캐시/키/로컬 배포 JSON은 포함하지 않는다.
기존 CURRENT_NAS 및 운영 YAML의 환경 메타데이터는 기존 복구 기록/설정을 유지한다.
저장소는 비공개로 유지해야 하며 개인화되지 않은 신규 설치는 예시 YAML을 이용한다.

## 기존 변경의 인계

- 직접 입력 가사와 검색 결과 가사를 구분하고 입력 초안을 보존한다.
- 수동 검색 가사/최종 태그 불일치 확인 및 저장 전후 항목별 결과 화면을 포함한다.
- 태그 저장 시 자동 파일명 변경은 비활성화하고 직접 파일명 변경 경로를 유지한다.
- 4개 검색 모드, 재검색 시 선택 후보·수동 편집·커버·가사 유지, 목록 키보드 이동을 포함한다.
- 스캔의 지연 메타데이터 읽기, 작업별 저장과 중복 fsync 제거, 저장 시간 진단을 포함한다.
- 기존 배포 스크립트 변경은 배포 시 이전 이미지의 rollback 태그를 보존한다. 자동 롤백은 아니다.

소스와 관련 테스트의 diff를 검토했다. 관련 과거 측정·배포 기록은
[SAVE_LATENCY_024](SAVE_LATENCY_024.md), [스캔 파이프라인](SCAN_PIPELINE_20261028.md),
[현재 NAS](CURRENT_NAS.md)에 보존한다. 기록에 기재된 과거 성공은 이번 커밋의 성공을 뜻하지 않는다.

## 설치 가능 여부와 검증 경계

소스·Docker 빌드 입력·의존성 제약·신규 Compose 예시와 운영/복구 문서가 있다.
실제 신규 설치에는 Docker/Compose, 인터넷, 볼륨 권한, 접근 제어 및 별도 데이터 백업이 필요하다.
Python 3.11 slim과 Debian 패키지 digest/버전은 완전히 고정되지 않아 바이트 단위 재현은 보장하지 않는다.
의존성의 알려진 이슈는 [기존 보안 감사](SECURITY_AUDIT_KO.md)를 참고한다. 이번에는 업데이트하지 않았다.

이번 작업은 대규모 테스트·브라우저 자동화·NAS 배포 금지 요청에 따라 정적/소규모 검사만 수행한다.
Git diff 공백 검사, 제외 규칙, 문서 링크·배포 입력·의존성 제약 및 비밀 패턴 검사를 사용한다.
Docker 실행 파일이 로컬 PATH에 없어 Compose config·이미지 빌드·실제 컨테이너 설치는 검증하지 못했다.
전체 Python 회귀·실제 화면·NAS·운영 음악 저장/복원은 실행하지 않았다.
운영 음악/작업 JSON/캐시/백업은 변경하거나 삭제하지 않았다.

## 다음 AI의 시작점

README → AGENTS → INSTALL_KO / OPERATIONS_KO / BACKUP_RESTORE_KO 순서로 읽는다.
스캔·가사·UI 구조는 SCAN_SERVICE / LYRICS_SERVICE / UI_JAVASCRIPT 문서를 참고한다.
최신 코드를 실제 배포하기 전 격리된 생성 데이터로 관련 기능과 data 호환성을 검증한다.
미저장 UI 초안과 메모리 캐시는 GitHub 또는 서버 재시작으로 복구되지 않는다.

## 이번 실행 결과

- 통과: test_gitignore.js (47개 제외 경로/18개 허용 경로), test_repository_readiness.js (문서 링크·배포 입력·31개 의존성 제약·비밀 패턴), test_p25_search_modes.js.
- 통과: deploy-nas.tests.ps1 로컬 보호 검사, Python AST 문법 검사, 브라우저 JavaScript 6개 문법 검사, PyYAML 예시 Compose 구조/분리 경로/포트 검사, git diff --check.
- 전송 예정 기존 27커밋 patch에서 개인키·GitHub/AWS 토큰의 알려진 서명 패턴이 발견되지 않았다. 패턴 검사는 모든 비밀값 부재를 보장하지 않는다.
- 실패: test_ui_save.js의 캐시 버전 기대값은 024-input2이나 현재 HTML은 028-keyboard2이다. test_p2_ui.js는 textarea의 textContent가 '검색 안 함'이라고 기대하나 현재 코드는 value/placeholder를 사용한다. 두 검사는 첫 실패에서 중단했으므로 뒤 검사의 통과 여부도 알 수 없다. 앱·테스트는 이번에 수정하지 않고 기존 상태로 보존했다.
- GitHub CLI(gh)가 PATH에 없다. 기존 Git 원격 인증으로 ls-remote는 성공했다. 실제 push 결과는 최종 보고의 커밋/원격 SHA 확인을 기준으로 한다.

두 UI 검사 실패 상태의 push는 AGENTS 규칙에 따라 사용자에게 별도 확인을 요청했다.