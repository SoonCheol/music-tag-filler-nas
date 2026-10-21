# 변경 기록

## Unreleased — 정식 운영 이름 이전

- Portainer 공식 API로 스택·프로젝트·서비스·컨테이너를 `music-tag-filler`로 이전.
- 검증된 `music-tag-filler-nas:v1.0.0` 이미지 적용. 기존 음악·data 경로, rw 마운트, 환경·포트 유지.
- 원본 정의/data 백업, 단일 인스턴스 이전 및 최종 Portainer active·컨테이너 running·웹 HTTP 200 확인.
- 배포 설정과 설치·복구·AI 인계 문서를 실제 운영 이름으로 정리. 기존 v1.0.0 태그·Release 유지.

## Unreleased — v1.0.0 정식 등록 작업

- 사용자 요청에 따라 운영 `/music:rw` 전환과 격리 음원 4종의 저장·원본 바이트 복원 검증 완료.
- 기존 소스·data·Portainer 정의 백업 및 v6 롤백 이미지 보존.
- 잠금 의존성의 새 v1.0.0 이미지 빌드 및 Python 회귀 55개 통과.
- 고정 운영 이름 `music-tag-filler`로의 이전과 GitHub 등록은 인증 대기 중이다.
  실제 완료 여부는 [등록 상태](docs/V1_REGISTRATION_STATUS.md)를 따른다.

## Unreleased — 장기 보관 준비

- NAS SSH/운영 상태 재확인 및 GitHub v1.0.0 릴리스 문안·등록 점검표 준비. 아직 발행하지 않음.
- 실제 NAS 구성·설치·업데이트·Git 관리·데이터/이미지 백업 및 복구 절차를 한글로 기록.
- 현재 v6 읽기 전용 음악 마운트와 일치하는 Stack/Compose 보관본 마련.
- 실제 NAS Python 환경 31개 패키지 버전 제약 및 빌드 context 제외 규칙 추가.
- 기존 자동 배포에 Dockerfile·requirements·.dockerignore 변경 전송 연결.
- 복구 파일 누락/비밀값 검사와 GitHub Actions 회귀 workflow 추가.
- 기존 Git 기록 유지. 이 작업은 아직 commit·push·운영 재배포하지 않음.

## 앞서 구현·배포한 P0/P1/P2 및 UI

- P0: 명시적 저장 범위·선택/수동값/체크 반영, 최초 원본 무결성 백업과 바이트 복원.
- P1: 국가별 검색·US 폴백, 후보 병합/검증, fpcalc, 커버/가사 검증과 오류 구분.
- P2: 경로·SHA 기반 이어하기, 식별자·파일명·커버 입력, 설정·작업 진단.
- UI: 폴더 임시 선택→선택 확정/닫기, 트리 상태 보관, 두 창 정렬,
  저장 옵션 모달과 확인/취소, ‘빈 태그만 채우기’·‘없는 가사 추가’ 모달 이동.
- 당시 Python 회귀 55개와 UI 테스트 통과. 상세 이력은 P0/P1/P2_VALIDATION.md 참고.

이 항목은 이미 운영 중인 동작의 설명이며, 정식 릴리스 태그나 원격 백업 완료를 뜻하지 않는다.
