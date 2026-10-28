# #022-v2 수동 가사 검색 검증·배포 기록

2026-10-27. 기준은 #021 NAS 배포본이다. AGENTS.md, README 관련 부분, CURRENT_NAS.md,
#021 변경·실제 소스와 기존 가사/저장/UI 검사를 확인했다.

## 수정 파일과 함수

| 파일 | 함수·영역 | 변경 |
| --- | --- | --- |
| app/static/js/lyrics.js | searchLyricsForCurrent, manualLyricTags, manualLyricQueryKey | 버튼 클릭 시 화면 Title/Artist를 직접 읽고, 미저장·체크와 무관하게 요청한다. 응답의 화면 조건 변경 검사도 같은 값으로 한다. |
| app/static/js/lyrics.js | renderLyricsPanels, renderManualLyrics, selectManualLyrics, applyLyricResult | 검색 결과 표시와 저장 적용 검사를 분리한다. 사용자가 승인한 최소 가사 후보 select 및 결과 없음/API 오류 안내. 추천 후보 적용 시 수동 안내 정리. |
| app/main.py | search_file_lyrics, lookup_lyrics | 수동 endpoint만 manual=True/length=0. 경로·파일 리비전·추천 후보 소유권 검사는 유지. |
| app/lyrics_service.py | lookup_lyrics, remember_lyrics, lyric_response, rekey_lyrics | 수동·자동 결과/진행 중 요청 캐시를 구분. 가사 후보별 기존 저장 토큰 재사용. 이름 변경 시 후보 토큰도 기존 리매핑을 따른다. |
| app/upstream/search_lyrics.py | find, pick, _record_result, LyricsResult | 수동만 길이 일치·끝 타임스탬프·문자량/초 검사 제외. 동일 제목/가수의 가사가 다른 후보도 conflict로 숨기지 않고 명시적 선택 가능. 제목/가수/버전/텍스트 기본 검증은 유지. 자동 판정은 기존 그대로. |
| app/static/index.html, app/static/css/style.css | 가사창 | 작은 후보 선택 select와 상태 표시. 기존 가사창 높이 유지. |
| app/static/js/tag-editor.js | resetDraft, applyPathChange | 새 수동 안내 초기화 및 후보별 가사 토큰 리매핑 연결. 태그 기록·이름 변경 규칙은 변경하지 않음. |

수동 가사 후보 목록은 이전에 없었다. 사용자에게 확인한 뒤 수동 검색에만 추가했다.
첫 유효 후보를 표시하고, 후보가 여러 개면 목록에서 다른 가사로 전환할 수 있다.
자동 후보 선택/확인 필요·자동 후보 가사 입력·확인 필요 후보 클릭·백그라운드 가사 조회,
자동 길이 판정·저장·LRC·작업 목록 정렬은 기존 경로를 유지한다.
새 운영 모듈·의존성·배포 입력·데이터 형식은 추가하지 않았다.

## 검색어와 실제 제공처 응답

제공처는 기존 LRCLIB `https://lrclib.net/api/search`이다. 수동 경로에서도 기존 두 검색을 재사용한다.

- 첫 요청: `track_name=너 때문에`, `artist_name=After School` → HTTP 200, 원본 후보 4건.
- 보조 요청: `q=AfterSchool 너 때문에` → HTTP 200, 원본 후보 0건.
- 기존 제목·가수·버전·가사 검증 후 선택 가능한 후보 1건: ID 10986136, LRCLIB 길이 241초.
- 수동 검색 결과는 found이며 파일 길이 0/180초 여부로 제외하지 않는다. 요청 params에는 duration이 없다.
- 같은 실제 응답을 자동 pick에 파일 길이 180초로 평가하면 none이다. 자동 길이 제한은 유지된다.
- 실제 가사 본문을 문서에 복제하거나 운영 음악에 저장하지 않았다.

## 검증

최종 Linux 명령:

```sh
docker run --rm --network none --read-only --tmpfs /tmp:rw,size=512m \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/app:/tests \
  --mount type=bind,source=/tmp/music-tag-022-v2/source/tests,target=/tests,readonly \
  -w /app music-tag-filler-nas:v2.0.0 python -B -m unittest \
  test_p22_manual_lyrics test_p12_lyrics_service test_p1_search \
  test_p2_workflow test_p5_command001 test_p6_job_store test_p4_operations
```

최종 이미지의 /app 코드를 사용했다. 운영 /music, /data 마운트 없음. 모든 음원과 runtime은 컨테이너 /tmp에 생성했다.
최종 실행은 108개 통과, 실패/오류/skip/예상 실패 0이다. 중간 반복 실행 수를 합산하지 않았다.
로그: NAS `/tmp/music-tag-022-v2/final-tests.log`.

- 새 tests/test_p22_manual_lyrics.py 5개: API 실제 매처, 241/300초와 파일 길이 차이, 끝 타임스탬프,
  다른 가사 후보·기존 제목/가수/버전 검증, 자동 conflict/길이 회귀, 캐시 모드 분리, 오류 구분,
  후보별 파일/리비전/검색어 토큰 보호 및 이름 변경 리매핑.
- 기존 P1/P2/P5/P6/P12/P4: 자동 판정/가사 입력·조회, 저장 옵션·다중 포맷·원본 보존·LRC·이름 변경·작업 정렬.
- Node test_p2_ui.js, test_ui_save.js, test_command007_ui.js 모두 통과.
  실제 input/button handler로 체크 켬/끔 × 빈 태그 옵션 켬/끔 네 조합에서 요청 제목·가수 확인.
  선택한 가사의 표시·토큰, 늦은 응답 차단, 검색 조건 변경, 기존 가사 직접 편집 보호와 후보 전환 안내 초기화 확인.
- Node test_repository_readiness.js 및 PowerShell tests/deploy-nas.tests.ps1 통과.
- 수정 파일 git diff --check와 문법 검사 통과. 기존 사용자 AGENTS.md 공백 변경은 보존했고,
  배포 스크립트 실행 프로세스에만 기존 #020과 같은 core.whitespace 예외를 적용했다.
- 로컬 Windows Python은 musicbrainzngs가 없어 import 단계 오류가 났다. 로컬 전체 Python 성공으로 계산하지 않고 위 Linux 검사로 검증했다.
- 최종 Linux 시험은 OK였으나 외곽 SSH 명령의 종료코드 인용에 오류가 있었다. 최종 로그의 108개/OK를 별도 확인한 뒤에만 배포했다.

실제 브라우저에서는 PC 루프백의 tests/serve_p22_manual_ui.py를 사용했다.
현재 UI와 실제 LyricsService/find/pick을 연결하고 외부 LRCLIB 응답만 명시적인 테스트 fixture로 대체했다.
생성 1초 음원에 241초·300초 가사 후보 두 개를 조회해 두 번째 선택 후 내용 변경을 확인했다.
체크 해제 상태, 빈 태그 옵션 켠 상태, 기존 저장된 제목·가수 보호/readOnly 유지,
결과 없음과 HTTP 502 구분을 확인했다. 요청은 lyrics-search 네 건뿐이며 저장 요청은 없었다.
음원 bytes hash와 mtime은 같았다. 예시 가사는 테스트임을 표시했고 운영 결과로 사용하지 않았다.

NAS 루프백 임시 웹 서비스는 SSH 포트 전달이 administratively prohibited로 차단되어 PC 검증으로 전환했다.
SSH 설정·권한은 바꾸지 않았고 임시 NAS 컨테이너와 터널은 종료했다.
app/tests 소스의 NAS 임시 경로 전송은 자동 검토 거부 후 사용자의 구체적 승인을 받고 진행했다.

## NAS 배포 및 보존

기존 deploy-nas.ps1의 CheckOnly/PreflightOnly 통과 후 BuildOnly로 이미지를 만들었다.
최종 이미지 검증 후 기존 서비스만 재생성했다. stack 32, 컨테이너/프로젝트 music-tag-filler,
태그 music-tag-filler-nas:v2.0.0, 포트·마운트·환경·설정·접근 권한 유지.

- 최종 실행 이미지: `sha256:f14f7ed3b893b878ace0e2d98aa62e2c42974809e86bf15d7583de916b13aa2d`.
- running, 재시작0. HTTP/폴더 API와 HTML/CSS/lyrics.js/tag-editor.js의 로컬·운영 바이트 일치.
- 최종 운영 실제 웹 화면의 기존 작업·편집값 복원, 가사 검색 버튼 활성화 및 새 UI 요소 존재 확인.
  운영 음악으로 검색/저장/스캔 테스트를 하지 않았다. 페이지의 기존 자동 미리보기 조회만 발생했다.
- 복귀 이미지: `music-tag-filler-nas:rollback-022-v2-20261027` → `sha256:431aee94e84f0441a160c943d613032f90cdf2766b21bed0929b51aedade20fc`.
- 변경 전 소스 백업: `/volume3/docker3/music-tag-filler-v6/deploy-backups/20261027-092821-1b5b56a0`.
  안내 정리 전 소스: `deploy-backups/20261027-093336-1eaa7fb0`. 실제 롤백은 수행하지 않았다.
- 기존 컨테이너 권한으로 /data 전체 파일을 읽었다. 배포 전후 622개, 960,745,425 bytes,
  집계 SHA-256 `ca028431097b83dfb36b46308af8624dcc26f39e20c32f923b15d63d43393201` 동일.
  정렬한 상대 경로+NUL+각 내용 SHA-256+개행을 집계했다. 과거 #021 문서의 집계 방식/해시와 혼동하지 않는다.
- 운영 음악 쓰기·이름 변경·복원·스캔과 GitHub push 없음.

## 남은 조건

수동 검색은 화면의 입력값을 사용한다. 기존 빈 태그 보호가 필드를 읽기 전용으로 바꾼 경우에는
그 순간 화면에 표시된 보호된 값을 조회한다. 검색을 위해 보호 규칙을 해제하지 않는다.
검색어와 최종 저장 대상 태그가 다르면 기존 보호에 따라 가사 저장에서 제외된다.
검색 성공은 자동 저장을 뜻하지 않는다. 이번 범위의 미해결 기능 오류는 확인되지 않았다.
기존 #021 배포본의 미커밋 변경은 aa5c076으로 별도 로컬 기록하여 #022 차이를 분리했다.
