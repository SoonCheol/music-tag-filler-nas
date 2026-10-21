# GitHub v1.0.0 등록 기록

**2026-10-21 발행 완료:** Private 저장소에 커밋
`2819fd96ef69adc83ca3fbf5ce0ba2520d3653fc`를 push하고 `v1.0.0` 태그와
[정식 Release](https://github.com/SoonCheol/music-tag-filler-nas/releases/tag/v1.0.0)를 등록했다.
아래 내용은 준비 당시의 초안/점검 기록이며, 최신 상태는 [등록 상태](V1_REGISTRATION_STATUS.md)를 따른다.
NAS 이름 이전은 Portainer 인증 대기 중이며 Release 본문에도 이 제한을 명시했다.

**최신 지시:** 사용자가 정식 운영 이름 `music-tag-filler`와 이미지 `music-tag-filler-nas:v1.0.0`으로
이전 및 등록을 요청했다. 아래 v6/ro 점검표는 과거 기록이다. 현재 rw와 새 이미지 검증,
인증 대기·잔여 절차는 [등록 상태](V1_REGISTRATION_STATUS.md)를 따른다.

## 버전과 대상

- 등록 예정: 비공개 `SoonCheol/music-tag-filler-nas`, 태그 `v1.0.0`.
- Release 제목 초안: **Music Tag Filler NAS v1.0.0 — 최초 백업·복구 기준판**.
- GitHub 버전 `v1.0.0`은 저장소의 최초 관리 버전이다. 프로그램 계열 v6,
  컨테이너 `music-tag-filler-v6`, 이미지 태그 `music-tag-filler-nas:v6`를 바꾸지 않는다.
- 현재 HEAD는 원본 커밋 `540725e7904ece20ec3b4d4757ed8da580585e81`이며
  기능·문서 변경은 아직 미커밋이다. 이 원본 HEAD에 v1.0.0 태그를 붙이면 안 된다.
- 이 문서는 로컬 문안/점검표다. GitHub의 Draft Release를 만든 상태도 아니다.

## 2026-10-21 13:19 KST 운영 점검

| 항목 | 확인 결과 |
| --- | --- |
| SSH | 기존 키로 hitmyhead 계정 연결 성공 |
| 컨테이너 | running, restarting=false, 재시작 횟수 0 |
| 운영 이미지 | `sha256:467fd3b7a2c2f254aff3f2b316ae4eda46e9dc725683a377e2408863d6f00ca0` |
| 음악 / data | 기존 호스트 경로 유지, `/music:ro`, `/data:rw` |
| 포트·환경 | 8000:8000, MUSIC_ROOT=/music, DATA_ROOT=/data, TZ=Asia/Seoul |
| 웹 | HTTP 200, 운영 HTML과 로컬 파일 동일 |
| 앱 소스 | 배포 허용 목록의 활성 앱 파일 17개와 운영 이미지 내부 SHA256 모두 동일 |
| 진단 | job_store_error=null, 설정/검색 기능 진단 오류 0 |
| 폴더 API | 3517개 반환 |
| AcoustID | fpcalc 사용 가능, API 키 미설정 |

위 점검은 읽기 전용이다. 컨테이너 재시작/재생성, 설정 저장, 스캔·음악 저장·복원은 하지 않았다.
Dockerfile·의존성 잠금·복구 YAML·문서 등 보관 준비 변경은 운영에 재배포하지 않았다.
기존의 별도 복구 검증 이미지 빌드 및 55개 회귀 결과는 [검증 보고서](READINESS_REPORT.md)를 따른다.

## Release 본문 초안

### 포함 기능과 복구 자료

- P0: 후보/수동 값/체크 반영, 명시적 저장 범위, 리비전 검증,
  최초 원본 백업·무결성 검사·정확한 바이트 복원·부분 실패 보고.
- P1: MusicBrainz/iTunes 국가별 검색과 폴백, 후보 병합/자동 선택 보호,
  fpcalc 연결, 커버/가사 검증·오류 구분.
- P2와 UI: 계층형 폴더 트리·선택 확정, 경로/SHA 기반 이어하기,
  식별자·이름 변경·커버 초안·설정 모달.
- 활성 전체 소스, Docker/Portainer 정의, 배포·테스트 코드, 라이선스,
  현재 환경 및 한글 설치·업데이트·백업·복구·AI 인계 문서.

### 검증과 알려진 제한

- 기존 별도 복구 이미지에서 생성 음원 P0/P1/P2 55개 통과.
  UI·배포 보호·업로드 제외·필수 파일 검사와 YAML 문법 검증 통과.
- 운영 음악은 `/music:ro`다. 태그 저장·이름 변경·되돌리기 성공 시험은 격리 음원에서만 수행했다.
- AcoustID 실제 외부 조회는 API 키 미설정으로 미검증이다.
- OSV 스냅샷에서 기존 Pillow·python-multipart·Requests·Starlette 4개 패키지에
  보안 공지가 일치했다. 이를 해결한 보안 강화판으로 소개하지 않는다.
  상세 범위와 후속 조치는 [보안 보고서](SECURITY_AUDIT_KO.md)를 참고한다.
- 새 NAS 실설치·실제 data/archive 복원 훈련·GitHub Actions 실행은 아직 하지 않았다.
- 소스/문서만으로 음악·설정 데이터·개인키를 복원할 수 없다. 별도 백업이 필요하다.
- 운영 메타데이터는 사용자 요청에 따라 포함하므로 저장소를 비공개로 유지한다.
  원본 키·API 키·음악·data·백업 archive는 Release 첨부에도 올리지 않는다.

## 실제 등록 전 남은 절차

1. 사용 가능한 GitHub 인증으로 대상 저장소가 실제로 존재하고 비공개인지,
   올바른 계정에 쓰기 권한이 있는지 확인한다.
2. 원격 브랜치·기존 `v1.0.0` 태그/Release 여부를 확인한다. 기존 내용을 덮어쓰지 않는다.
   현재 비인증 API 조회의 404는 ‘저장소 없음’의 증거가 아니다.
3. 변경 파일과 보안·라이선스 제한을 검토한다. 기존 4개 패키지 보안 공지의 미해결 상태를
   첫 비공개 백업 릴리스에 포함할지 사용자가 판단한다. 의존성은 임의로 업그레이드하지 않는다.
4. 사용자가 명시적으로 요청한 뒤에만 검토한 파일을 stage/commit한다.
   기존 Git 기록은 유지하고, 새 릴리스 커밋 SHA를 이 문서/릴리스 기록에 남긴다.
5. 별도 요청 범위 안에서 원격 연결 및 브랜치 push를 수행한다.
   원본 HEAD·미커밋 상태에 태그를 만들거나 force push하지 않는다.
6. GitHub Actions 결과를 실제로 확인한다. 실패하거나 실행하지 못한 항목은 그대로 공개한다.
7. 승인한 새 커밋에 `v1.0.0` 태그와 위 문안의 Release를 등록한다.
   GitHub가 생성하는 소스 archive 외에 개인 data/이미지/키/백업 파일을 첨부하지 않는다.

## 현재 미완료 상태

이번 확인에서는 Git Credential Manager/환경변수의 사용 가능한 GitHub 인증 정보가 없었다.
비인증 저장소 조회는 404였으므로 비공개 여부·쓰기 권한·태그/Release 존재 여부를 검증하지 못했다.
로컬 원격·태그도 없으며 stage·commit·push·Release 등록을 수행하지 않았다.
