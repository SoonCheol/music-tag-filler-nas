# 2단계 P1 구현·검증 및 배포 결과

> 업로드 준비 과정에서 개인 NAS 주소·경로는 예시로 치환했다. 아래 날짜·테스트 결과는 당시 기록이며, 예시 주소 자체에 접속해 검증한 것은 아니다.

기준일: 2026-10-21 KST. `FEATURE_COMPARISON.md`의 P0 이전 감사와
`P0_VALIDATION.md` 이후 구현이다. 원본 커밋
`8996e2daa74c787395ebbf3f9d871b1484f4aafe`의 MIT 코드를 재사용했다.

## 구현 내역과 코드 근거

| 범위 | 구현 상태 및 동작 | 주요 코드 |
| --- | --- | --- |
| 국가별 검색 | 구현. KR/US/JP/CN/TW/HK/GB/DE/FR, iTunes 국가→US 폴백. 원본 규칙에 따라 KR 음악 카탈로그 요청은 US로 직접 대체. MB 필드 검색→자유 검색, 공식 원본 앨범 우선, 아티스트 크레딧·식별자 수집 | `app/upstream/search_itunes.py`, `search_mb.py` |
| 병합·점수·자동 선택 | 구현. 동일 소스의 정확한 중복 제거, 소스 간 동일 녹음 병합, 제목·가수·길이·출처 점수. 90점 미만, 일반 파일명, 다른 버전, 길이 불일치, 비슷한 점수의 다른 곡은 자동 선택 차단. 명시적 수동 선택은 허용 | `app/search_service.py:rank`, `auto_pick` |
| AcoustID | 구현, 실서비스 키 미설정. 실제 fpcalc→지문·재생시간 POST→상위 3개 MB 정보 보강. 텍스트 무결과 시 대체 검색, 명시적 음향 검색 가능. 키·실행 파일 누락을 오류로 반환 | `app/upstream/search_acoustid.py`, `pipeline.py`, `app/search_service.py:sound` |
| 수동 재검색·적용 | 구현. 기존 입력창/버튼·Enter 사용. 새 후보 ID와 파일 SHA256 검증, 오래된 검색 결과 차단, 수정 중 값·체크 유지, 후보 선택 후 P0 저장 계약 사용 | `app/main.py:research_file`, `app/static/index.html:manualSearch` |
| 커버 | 구현. 4형식 기존 커버 읽기, 후보 URL→CAA release-group→iTunes 앨범 대체 검색. 20MB/25MP 제한·이미지 검증·JPEG/최대1000px 변환, 제한된 메모리 캐시. 저장 실패/부분 성공 보고 | `app/search_service.py:prepare_image`, `fetch_cover`, `app/main.py:save_one`, `app/upstream/tags.py` |
| 가사 | 구현. 원본 LRCLIB 제목·가수·버전·±3초·마지막 타임스탬프·내용 길이·충돌/복제·원문 우선 검증. 두 검색 결과를 함께 판단. 503 재시도와 BUSY 재조회, 연속 실패 제한. 기존 실제 가사 보호, 마커만 교체 가능 | `app/upstream/search_lyrics.py`, `net.py`, `app/main.py:save_one`, `app/storage.py` |
| 실패 구분 | 구현. 무결과/일부 소스 실패/전체 실패/취소, 네트워크·HTTP·응답 형식·429/503·필수 설정·손상 이미지 오류 분리. LRCLIB 실패는 원본의 안전한 `busy` 상태로 묶고 저장 결과에 경고 | `app/search_service.py:network_error`, `search`, `app/upstream/net.py` |

## 사용·설정

- 기존 재검색 입력: `가수 - 제목`. 국가 지정: `@JP 가수 - 제목`.
  음향 검색: `@sound`, 또는 `@JP @sound`.
- 기본 국가는 KR. 기존 `/data/settings.json`의 JSON 객체에 `"country":"JP"`를
  추가할 수 있다. 기존 설정을 통째로 덮어쓰지 않는다. API 요청의 `country`도 지원한다.
- AcoustID 애플리케이션 키는 <https://acoustid.org/new-application>에서 발급한다.
  기존 data 마운트의 `acoustid_key.txt`에 실제 키만 기록하면 다음 검색부터 읽는다.
  NAS 경로: `/srv/docker/music-tag-filler-v6/data/acoustid_key.txt`.
  설정 객체의 `acoustid_key`도 지원한다. API는 키 자체를 반환하지 않는다.
- 환경변수·Docker 볼륨은 이번 작업에서 변경하지 않았다. 임의의 운영 키도 만들지 않았다.

## 격리 회귀 테스트

검증 폴더: `/srv/docker/music-tag-filler-v6/p1-validation-20261021`.
운영 `/music`·`/data`를 연결하지 않고 컨테이너 `/tmp`에서 ffmpeg 생성 음원만 사용했다.

```sh
docker run --rm --network none --read-only --tmpfs /tmp:rw,size=512m \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v /srv/docker/music-tag-filler-v6/p1-validation-20261021:/workspace:ro \
  -w /workspace music-tag-filler-nas:v6 \
  python -m unittest discover -s tests -p 'test_p*.py' -q
```

- **37개 통과, 실패·스킵 0**: 기존 P0 21개 + P1 16개.
- P0: 선택 범위·마스크·후보 ID·90점·오래된 SHA·읽기 전용·백업 실패/손상·동시 저장·부분 실패·이름 변경·최초 원본 보존·정확한 바이트 복원 유지.
- P1: 국가/US 폴백, MB 재검색·공식 발매 우선, 중복 병합·자동 선택 차단,
  실제 15초 생성 FLAC 지문과 SHA 불변, 모의 AcoustID POST·키 오류·누락,
  무결과 음향 대체·일부 API 제한·취소·오류 구분, 이미지 손상/변환/캐시/CAA 대체,
  LRCLIB 버전·시간·충돌·과다 텍스트·503 backoff, HTTP 재검색→수동 저장 및 SHA 충돌,
  4형식 커버와 가사 마커 저장→원본 바이트 복원을 검증했다.
- 외부 API 응답은 회귀 테스트에서 모의 처리했다. 실제 음악 파일은 사용하지 않았다.
- `node tests/test_ui_save.js`: 통과. 기존 P0 요청·초안 유지와 국가/음향 재검색 요청 확인.
- `tests/deploy-nas.tests.ps1`: 통과. 정상 설정 및 7개 위험한 설정 변경 거부 확인.
- P0 수동 후보 테스트의 고정 제목 기대값을 실제 두 번째 행 제목으로 변경했다.
  P1 점수 정렬로 행 순서가 바뀌어도 두 번째 후보 저장 검증을 유지한다.
- 수정 전 P1 기준 HTML/CSS 영역이 바이트 동일함을 확인했다. `git diff`·`git diff --check` 확인 완료.

## 실제 API·배포 확인

- 기존 `deploy-nas.ps1`의 SSH 키·legacy SCP·변경 파일 백업/전송·이미지 빌드·v6 단독 재생성을 사용했다.
  추가 모듈만 기존 허용 목록에 등록했다. sudo 및 권한 변경 없음.
- 백업: `/srv/docker/music-tag-filler-v6/deploy-backups/20261020-200644-ca20759e`
  (폴더 이름은 실행 환경 시각 기준).
- 배포 이미지: `sha256:18465d2270c16918fa8a3d6278304225ce981b60f2640c831abd4ae03cf98a33`.
- 스크립트에서 새 이미지·실행 상태·기존 설정/마운트 동일·웹/폴더 API를 확인했다.
- Windows에서 <http://nas.example.invalid:8000/> **HTTP 200** 확인.
  `/api/capabilities`: 기본 KR, 9개 국가, fpcalc 사용 가능, 키 없음, 설정 오류 없음.
- 운영 볼륨 없는 별도 컨테이너에서 실제 `The Beatles - Yesterday` 조회:
  **MusicBrainz+iTunes 20개 후보, 오류 없음 / LRCLIB found 630자 / 검증 커버 221798바이트**.
  음악 저장은 하지 않았다. 재현 도구: `tests/probe_p1.py` (외부 네트워크 필요).

## 미완성·검증 한계

- **AcoustID 실제 외부 조회는 미검증**: 운영 키가 없어 활성화할 수 없다.
  지문 생성과 모의 조회/오류 경로는 통과했다. 키 설정 후 실제 등록 음원의
  읽기 전용 음향 조회로 추가 확인이 필요하다. 성공으로 간주하지 않는다.
- 가사는 커뮤니티 데이터이므로 검증을 통과하지 못하면 추가하지 않는다.
  LRCLIB의 개별 네트워크/제한 원인은 `busy`로 통합되며 무결과와는 구분된다.
- `/music:ro`를 유지하므로 운영 음악 저장·복원은 계속 차단된다.
  저장·복원 성공은 격리된 생성 음원에서만 확인했다.
- 9개 국가 전체의 실시간 카탈로그 및 모든 곡의 검색 품질을 보장하지 않는다.
  실제 외부 확인은 위 한 곡이며, 국가 폴백과 예외 처리는 모의 회귀 검증이다.
