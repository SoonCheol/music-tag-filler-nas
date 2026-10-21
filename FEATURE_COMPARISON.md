# Music Tag Filler 원본과 NAS v6 전체 기능 비교

> 이 표는 **1단계 P0 수정 전**의 감사 기록이다. 당시 판정과 코드 줄 번호를 역사적 근거로 유지한다. 이후 저장 계약·후보 검증·필드 보호·무결성 백업·실제 복원 개선의 구현 및 검증 결과는 [P0_VALIDATION.md](P0_VALIDATION.md)를 참고한다. 이 문서의 과거 ‘미구현’ 판정을 현재 상태로 해석하지 않는다.

> 2단계 검색·음향 지문·커버·가사 구현과 현재 제한 사항은 [P1_VALIDATION.md](P1_VALIDATION.md)에 기록한다.

> 3단계 P2 기능별 구현·회귀 테스트·실제 NAS 배포와 UI 검증 한계는 [P2_VALIDATION.md](P2_VALIDATION.md)에 기록한다.

## 1. 비교 기준과 검증 범위

- 작성 기준일: 2026-10-21.
- 원본 저장소: <https://github.com/microhan1/music-tag-filler>.
- 원본 기준 커밋: [`8996e2daa74c787395ebbf3f9d871b1484f4aafe`](https://github.com/microhan1/music-tag-filler/tree/8996e2daa74c787395ebbf3f9d871b1484f4aafe), 커밋 시각 2026-10-15 01:10:36 UTC.
- 확인한 원본 파일: `README.md`, `main.py`, `gui.py`, `pipeline.py`, `tags.py`, `match.py`, `search_itunes.py`, `search_mb.py`, `search_acoustid.py`, `search_lyrics.py`, `net.py`, `prefs.py`, `i18n.py`, `update_check.py`.
- NAS 비교 대상: 실제 실행되는 `app/main.py`, `app/static/index.html`, 의존성 및 Docker 설정. `main_1.py`, `main_new.py`, `index_1.html`, `index_new.html`은 실행 대상이 아니므로 기능 구현의 증거로 사용하지 않았다.
- UI 디자인은 비교하지 않았다. 버튼·입력란의 존재는 기능 완성으로 인정하지 않고, 입력 → 상태 변경 → 서버 요청 → 파일 처리 흐름을 확인했다.
- 소스 검토와 NAS 읽기 전용 조회를 수행했다. 음악 파일 저장·가사 추가·표지 쓰기·복원 시험은 수행하지 않았다. 따라서 모든 파일에 대한 실행 성공이나 외부 API의 현재 검색 품질을 보증하는 문서는 아니다.
- NAS 소스 두 파일의 SHA256은 Windows 소스와 일치했다. 이 문서의 코드 줄 번호는 작성 시점 기준이며, 함수 이름도 함께 기록했다.

### 구현 상태

| 상태 | 의미 |
| --- | --- |
| 정상 | 해당 범위의 코드 흐름이 연결되어 있거나 읽기 전용 확인으로 동작을 확인했다. 모든 예외·파일 형식의 실파일 회귀 시험을 통과했다는 뜻은 아니다. |
| 일부 | 실행 경로는 있지만 원본의 주요 조건·형식·보호 로직이 빠졌거나, 화면과 서버 사이 연결이 불완전하다. |
| 미구현 | 실행 로직이 없거나 빈 함수·미정의 함수·표시만 존재한다. |

### 개선 우선순위

| 우선순위 | 적용 기준 |
| --- | --- |
| P0 | 잘못된 대상 저장, 기존 데이터 보호, 신뢰할 수 있는 백업·복원, 실패를 성공으로 오인하는 문제. 실제 쓰기 기능을 허용하기 전에 해결할 사항. |
| P1 | 후보 적용·검색·커버·가사의 핵심 기능과 정확성 복구. |
| P2 | 입력 편의, 식별자, 이름 변경, 작업 복구와 진단 개선. |
| P3 | CLI·언어·업데이트 알림 등 NAS에서 이식 여부를 선택할 수 있는 기능. |
| 유지 | 현재 범위를 보존하고 회귀 확인할 사항. 새 기능 개발 우선순위는 아님. |

## 2. 핵심 결론과 현재 NAS 실행 조건

NAS v6는 원본의 검색·표시 기능 일부와 NAS용 작업 관리를 구현했지만, 원본의 안전한 저장·복원 기능을 완전히 이식한 상태는 아니다.

특히 다음은 명확한 기능상 누락이다.

1. 화면에서 고른 후보·직접 고친 값·항목별 체크 상태가 저장 API로 전달되지 않는다.
2. 서버의 `best`는 점수와 무관한 첫 후보이며, 저장 API는 90점 조건을 검사하지 않는다.
3. MP3/M4A 가사 쓰기에 사용한 `lyrics` 키는 설치된 Mutagen Easy 인터페이스에서 지원하지 않는다. 발생한 예외를 무시한다.
4. AcoustID는 옵션·설치 패키지만 있고 지문 생성과 조회 호출이 없다.
5. 음악 태그 백업은 기본 태그 JSON에 불과하며, 원본 파일 재구성에 필요한 정보를 보관하지 않는다.
6. 되돌리기 API는 백업 JSON을 읽고 경로를 반환할 뿐 파일을 복원하지 않는다.

### 실제 NAS 상태 확인

| 항목 | 확인값 | 의미 |
| --- | --- | --- |
| 컨테이너 | `music-tag-filler-v6` | 실제 실행 대상 |
| 이미지 | `music-tag-filler-nas:v6` | 배포된 이미지 태그 |
| 이미지 ID | `sha256:753a24e399e9d2da575348636604c9f25e2701d420d4a5960d5d6352a981fa76` | 비교 당시 실행 이미지 |
| 음악 마운트 | `/srv/music` → `/music`, `Mode=ro`, `RW=false` | 현재 실제 태그·커버·가사 저장과 파일명 변경은 불가능 |
| 데이터 마운트 | `/srv/docker/music-tag-filler-v6/data` → `/data`, `RW=true` | 작업 상태 기록용 쓰기 가능 |
| `app/main.py` SHA256 | `6d21ac06b6bf2eac813625deff6357c41c391848c97203a66b2b84e891c1a9bd` | Windows/NAS 일치 |
| `app/static/index.html` SHA256 | `fc0dee7dc6a3230eea54c793f0212388ddab24ecdd0aff6fb8a3eb7b2393454c` | Windows/NAS 일치 |

**코드의 구현 상태와 배포 환경의 쓰기 가능 여부는 별개다.** 아래 표에서 저장 기능이 ‘일부’라고 해도 현재 `/music:ro`에서는 실제 파일 변경이 허용되지 않는다. 이는 의도적으로 유지한 기존 설정이며, 이 문서는 읽기·쓰기 마운트 변경을 승인하거나 제안하는 작업 지시가 아니다.

## 3. 파일 입력·정보 읽기·검색

| ID | 기능 | 원본 구현 | NAS 상태 | NAS 차이점·코드 근거 | 우선순위·개선 방향 |
| --- | --- | --- | --- | --- | --- |
| F01 | 폴더 및 하위 폴더 탐색 | `tags.collect_files()`가 재귀 탐색 지원 | 정상 | [N-SCAN] `scan_job()`에서 `root.rglob()`으로 선택 폴더 이하 탐색 | 유지: 폴더 경계와 지원 형식 회귀 확인 |
| F02 | 개별 파일·여러 경로 입력 | 파일/폴더 대화상자, 파일 드롭, CLI 입력과 중복 제거 | 미구현 | [N-UI] 현재 입력은 폴더 선택 기반. 개별 파일 추가·여러 경로 누적 API/동작 없음 | P2: NAS 내 개별 파일 선택이 필요한 경우 추가 |
| F03 | 하위 폴더 포함 여부 선택 | `recurse` 선택 및 CLI `--no-recurse` | 미구현 | [N-SCAN] 항상 재귀 탐색 | P2: 비재귀 탐색 옵션 검토 |
| F04 | MP3·FLAC·M4A·OGG 기본 텍스트 정보 읽기 | `tags.read_file()`이 형식별 처리 | 정상 | [N-READ] Mutagen으로 제목·가수·앨범·앨범아티스트·연도·장르·트랙·재생시간 읽기 | 유지: 태그 없는 파일과 형식별 회귀 확인 |
| F05 | 포맷·비트레이트·샘플레이트 등 상세 정보 | `FileInfo`에 형식·길이·비트레이트·샘플레이트 보관 | 일부 | [N-READ] 길이만 수집. 비트레이트·샘플레이트는 수집하지 않음 | P2: 필요한 상세 정보 추가 |
| F06 | 지원 확장자와 실제 처리 범위 일치 | 원본은 MP3·FLAC·M4A·OGG 명시 | 일부 | [N-SCAN] MP4·WMA·WAV도 수집하나, 이를 원본 수준의 태그·커버·가사 지원으로 볼 수 없음 | P1: 확장자별 읽기/쓰기 지원표와 오류 처리 확정 |
| F07 | 파일명에서 가수·제목 추출 | 트랙번호·불필요한 표시 제거, 다양한 대시, 버전 표시 처리 | 일부 | [N-PARSE] `parse_filename()`은 `" - "`만 한 번 분리 | P1: 원본 파싱과 버전 처리 이식 |
| F08 | 기존 태그를 검색 힌트로 사용 | `pipeline.initial_query()`가 기존 정보 우선 | 정상 | [N-SCAN] 기존 가수·제목이 있으면 파일명 힌트보다 우선 사용 | 유지 |
| F09 | MusicBrainz 검색 | 필드 검색과 일반 검색 대체 경로, 제목 버전 처리 | 일부 | [N-MB] 단일 쿼리만 사용. 별칭·일반 검색 폴백 없음 | P1: 원본 쿼리 구성·폴백 적용 |
| F10 | 적절한 발매·복수 가수 정보 선정 | 공식 발매·앨범 종류·날짜 기준 선택, 복수 크레딧·트랙·장르 수집 | 일부 | [N-MB] 첫 가수와 첫 발매를 사용하고 트랙은 `None` | P1: 발매 선정 및 메타데이터 추출 개선 |
| F11 | iTunes 기본 검색 | 국가별 곡 검색과 상세 후보 수집 | 일부 | [N-IT] KR만 조회하고 후보 필드도 원본보다 적음 | P1: 실제 검색 국가 및 후보 정보 복구 |
| F12 | 검색 국가 선택·US 폴백 | 여러 국가, 빈 스토어 회피, 미국 폴백 | 미구현 | [N-IT] `country="KR"` 고정. US 재조회 없음 | P1: 국가 선택과 폴백 구현 |
| F13 | 출처별 동일 녹음 후보 병합 | `match.merge()`가 제목·가수·길이·앨범을 대조해 출처와 정보 병합 | 미구현 | [N-SCAN] 후보 목록을 이어 붙여 정렬만 함 | P1: 중복 병합 및 출처 정보 보존 |
| F14 | 공통 일치도 점수 | 제목·가수 유사도, 재생시간, 출처 신뢰도, 지문 점수 반영 | 일부 | [N-IT]/[N-MB] iTunes는 문자열 포함 검사 최대 80점, MB는 검색 반환 점수. 동일 기준이 아님 | P1: 원본 공통 점수 체계 적용 |
| F15 | 90점 이상 자동 선택 | `pipeline.auto_pick()`이 90점 및 유효 검색어 검사 | 일부 | [N-SCAN] `auto_apply`만 기록. `best`는 항상 첫 후보이고 [N-SAVE]는 점수 검사 없음 | **P0**: 자동/수동 선택 상태를 분리하고 저장 대상을 검증 |
| F16 | 무의미한 파일명 자동 선택 방지 | `track01`, 숫자 파일명 등의 `weak_query` 차단 | 미구현 | [N-PARSE]/[N-SCAN] 해당 판별 없음 | **P0**: 엉뚱한 후보 자동 저장 경로 차단 |
| F17 | 검색어 수정 후 재검색 | GUI `search_text()`와 검색 파이프라인 연결 | 미구현 | [N-MANUAL] `manualSearch(){}` 빈 함수 | P1: 재검색 API와 결과 갱신 연결 |
| F18 | AcoustID 음향 지문 검색 | `fpcalc` → AcoustID → 상위 MB 녹음 상세 보완 → 순위 산정 | 미구현 | [N-OPTIONS] `use_fingerprint` 값만 수신. [N-SCAN]은 텍스트 검색만 호출. [N-DEPS] 설치는 실행 연결의 증거가 아님 | P1: 키·fpcalc 검사, 지문 생성, 조회·보완 구현 |
| F19 | 텍스트 결과가 없을 때 소리 검색 | 원본 CLI의 자동 대체 및 GUI의 명시적 소리 검색 | 미구현 | [N-SCAN] 후보가 없어도 음향 검색 호출 없음 | P1: 명시적 검색과 필요한 대체 경로 구성 |
| F20 | 검색 오류 분리·일부 출처 실패 처리 | `SearchResult.errors`와 네트워크/제한/지문/키 오류 구분 | 일부 | [N-IT]/[N-MB] 예외를 `[]`로 바꿔 실패와 결과 없음 구분 불가 | P1: 결과와 오류를 분리해 전달 |
| F21 | API 호출 제한·429/503 재시도 | `net.py` 공통 제어, 대기 콜백, 취소 가능한 재시도 | 일부 | [N-SCAN] 파일 간 0.25초 대기. 원본 공통 제어 없음. MB 라이브러리 자체 동작과 동일시할 수 없음 | P1: 출처별 속도 제한·재시도·타임아웃 정책 이식 |
| F22 | 오프라인 상태와 검색 취소 | 온라인 확인, 상태 안내, 네트워크 대기 중 취소 | 일부 | NAS는 파일 사이 중지 요청 확인. 진행 중 HTTP 호출 자체는 즉시 취소하지 못함 | P2: 실패 원인과 중지 대기 상태 명확화 |

원본 근거: [O-TAGS], [O-MATCH], [O-PIPELINE], [O-ITUNES], [O-MB], [O-ACOUSTID], [O-NET], [O-GUI], [O-MAIN].

## 4. 후보 적용·태그 저장·파일명 변경

| ID | 기능 | 원본 구현 | NAS 상태 | NAS 차이점·코드 근거 | 우선순위·개선 방향 |
| --- | --- | --- | --- | --- | --- |
| S01 | 후보 클릭 후 정보 확인 | 후보를 확인하고 적용할 수 있음 | 정상 | [N-CAND] 클릭한 후보를 브라우저 입력칸과 커버에 표시 | 유지: 실제 저장과 구분 |
| S02 | 선택한 후보를 저장 대상으로 적용 | `FileState.selected/values/pending_ids`를 저장 흐름에서 사용 | 일부 | [N-CAND] 브라우저의 `r.best`만 변경. [N-UI-SAVE]는 경로만 보내며 서버 상태 갱신 없음 | **P0**: 후보 ID/값을 서버에 전달하고 검증 |
| S03 | ‘선택 적용’ 실행 | `App.apply_selected()` 구현 | 미구현 | [N-APPLY] 버튼이 호출하는 `applySelectedCandidate()`가 정의되지 않음 | P1: 동작 정의 및 저장 상태 연결 |
| S04 | 직접 편집한 값 저장 | `_on_field_edit()` → `FileState.values` → `current_tags()` → 저장 | 미구현 | [N-UI-SAVE] 편집한 `chg_*` 값이 요청에 없음 | **P0**: 사용자 입력과 저장 데이터 일치 |
| S05 | 항목별 변경 체크 반영 | 원본의 명시적 적용·수동 편집과 기존 값 보호 원칙에 대응 | 미구현 | NAS 고유 체크 UI가 있지만 `toggleAllChange()`는 체크 표시만 변경. [N-UI-SAVE]에 필드 마스크 없음 | **P0**: 체크 안 한 필드는 서버에서 보존 |
| S06 | 기본 텍스트 태그 쓰기 | 7개 필드: 제목·가수·앨범·앨범아티스트·연도·트랙·장르 | 일부 | [N-WRITE] 제목·가수·앨범·연도·트랙만 처리. 앨범아티스트·장르 쓰기 없음 | P1: 포맷별 전체 필드 매핑 및 실파일 검증 |
| S07 | 빈칸만 채우기 | 자동 선택은 기존 값 보존, 수동 적용은 명시적 변경 허용 | 일부 | [N-WRITE] 5개 기본 태그의 `set_if()`에만 적용. 가사·커버는 제외 | **P0**: 텍스트·가사·커버 보호를 일관되게 적용 |
| S08 | 빈 값으로 태그 삭제 | 원본 `write_file()`은 빈 텍스트 필드 제거 | 미구현 | [N-WRITE] 빈 값은 건너뛰며, 수동 입력도 미전달 | P1: 유지/설정/삭제를 구분한 요청 모델 |
| S09 | 개별 파일 저장 | 현재 파일의 실제 변경 상태 저장 | 일부 | 경로 지정은 되지만 서버에 남은 최초 후보 사용. 현재 `/music:ro`로 실제 쓰기 불가 | **P0**: 저장 대상·최종 값·권한을 정확히 판정 |
| S10 | 선택·전체 저장 | 파일별 변경 상태를 모아 저장 | 일부 | [N-UI-SAVE]/[N-SAVE] 체크된 경로는 전달. 체크가 없으면 빈 배열이 서버에서 작업 전체로 해석됨 | **P0**: ‘선택 없음’과 ‘전체’ 명시적 구분 |
| S11 | 필터된 목록과 저장 범위 일치 | 사용자 확인 대상과 저장 대상이 일치해야 함 | 일부 | [N-UI-SAVE] 화면 확인 문구는 필터 결과 개수지만 무선택 시 서버 작업 전체 저장 가능 | **P0**: 실제 저장 경로 목록/개수로 확인 |
| S12 | 변경 없는 파일 건너뛰기 | `dirty()`·저장 상태·가사 필요 여부 판단 | 미구현 | [N-SAVE] `best`가 있으면 쓰기 시도. 변경 여부 검사 없음 | P1: 불필요한 쓰기·백업 갱신 방지 |
| S13 | 저장 실패·부분 성공 보고 | 잠금·깨진 백업·커버 실패·이름 변경 실패 구분 | 일부 | [N-SAVE] 오류 배열 반환, 작업은 실패가 있어도 `saved`. [N-UI-SAVE]는 저장 개수만 표시 | **P0**: 오류·부분 성공을 숨기지 않고 상태 분리 |
| S14 | 저장 후 파일 정보 갱신 | 저장 후 다시 읽어 현재 상태 갱신 | 미구현 | [N-SAVE] 결과의 원본 태그·저장 후 경로·화면 상태를 갱신하지 않음 | P1: 저장 결과를 기준으로 상태 재동기화 |
| S15 | 파일명 변경 | 최종 태그로 안전한 이름 생성, 충돌 시 번호 부여 | 일부 | [N-WRITE] 서버 옵션은 있으나 [N-SCAN-UI]는 `rename:false` 고정. 충돌 시 건너뛰며 결과 경로도 갱신하지 않음 | P2: 옵션 연결·충돌 처리·새 경로 반환 |
| S16 | 파일과 백업 함께 이름 변경 | 둘 다 이동하거나 실패 시 원래 상태 보존 | 미구현 | [N-WRITE] 음악 파일만 `rename()`하며 백업은 옛 이름에 남음 | **P0**: 이름 변경과 백업 연계 복구 |
| S17 | MusicBrainz·iTunes 식별자 저장 | 아티스트·앨범아티스트·발매·녹음 ID, iTunes 아티스트 ID 저장 | 미구현 | [N-MB] 일부 녹음 ID를 후보에 보관하나 [N-WRITE]에서 기록하지 않음 | P2: 포맷별 ID 매핑 및 복수 ID 보존 |
| S18 | 정렬 이름·표시용 원문/로마자 선호 | `Ids` 및 `artist_name_preference` 적용 | 미구현 | NAS에 해당 설정·후보 정보·쓰기 경로 없음 | P2: 필요 시 원본 로직 이식 |

원본 근거: [O-GUI] `FileState`, `_apply_values()`, `apply_selected()`, `_save_job()`; [O-PIPELINE] `apply_candidate()`, `save_file()`; [O-TAGS] `write_file()`, `rename_target()`, `rename_file()`.

### 후보 선택·수동 입력의 단절 지점

```text
NAS 현재:
후보 클릭 → 브라우저 r.best / chg_*만 변경
저장 클릭 → [파일경로]만 전송
서버 save_job() → 서버 jobs.results의 기존 best 사용

원본:
후보 적용/수동 편집 → 파일별 values/pending_ids/cover_changed 갱신
저장 → 해당 파일의 current_tags()와 변경된 커버·식별자 사용
```

따라서 NAS에서 두 번째 후보를 고르거나 제목을 수정해도, 그 값이 서버에 전달되지 않아 최초 후보 기준으로 저장을 시도한다. 현재 음악 마운트는 읽기 전용이므로 이 오류가 실제 음악 파일에 반영되는 쓰기 시험은 수행하지 않았다.

## 5. 앨범 커버

| ID | 기능 | 원본 구현 | NAS 상태 | NAS 차이점·코드 근거 | 우선순위·개선 방향 |
| --- | --- | --- | --- | --- | --- |
| C01 | 후보 커버·확대 미리보기 | 후보 이미지 조회·미리보기 | 정상 | [N-CAND] 후보 URL 표시 및 화면 경계를 고려한 확대 위치 처리 | 유지 |
| C02 | 기존 내장 커버 읽기 | 형식별 커버 추출, 필요한 시점에 로드 | 미구현 | [N-READ] 커버 반환 없음. [N-SELECT] 현재 커버를 항상 `no image`로 설정 | P1: 내장 이미지 조회 API 및 형식별 읽기 |
| C03 | 커버 다운로드 및 저장 | MP3·FLAC·M4A·OGG 형식별 저장 | 일부 | [N-WRITE] MP3 APIC 삽입만 구현. 다른 형식 쓰기 없음 | P1: 전체 형식 지원 |
| C04 | 기존 커버 보호·교체 | 자동 선택 시 기존 표지 유지, 수동 적용 시 변경 | 미구현 | [N-WRITE] `only_empty`와 무관하게 URL이 있으면 APIC 추가. 기존 커버 존재 확인·전체 교체 규칙 없음 | **P0**: 기존 커버 보호 및 명시적 교체 |
| C05 | JPEG 변환·최대 크기 제한 | `prepare_cover()`가 긴 변 1000px 기본 제한, JPEG 처리 | 미구현 | iTunes URL 문자열만 변경. 원본 바이트를 검증·변환하지 않고 MIME을 JPEG로 지정 | P1: 실제 이미지 형식 검증·리사이즈·변환 |
| C06 | 커버 다중 출처 폴백 | 후보 URL → CAA release-group → iTunes 앨범 검색 | 미구현 | [N-WRITE] 후보 URL 한 번 조회, 실패 시 예외 무시 | P1: 폴백과 실패 상태 반환 |
| C07 | 로컬 이미지 선택·드롭 | `_cover_dialog()`, `_set_cover_from_file()`, 이미지 검증 | 미구현 | 실행 UI/서버에 이미지 입력·보관·저장 연결 없음 | P2: 검증된 업로드·적용 경로 추가 |
| C08 | 같은 표지를 목록 전체에 적용 | 원본 `apply_cover_to_all()`이 저장 전 변경 상태만 갱신 | 미구현 | NAS 실행 코드에 동작 없음 | P2: 개별 저장 보호가 완성된 뒤 구현 |
| C09 | 이미지 캐시·메모리 관리 | `CoverStore`와 썸네일·미리보기 캐시 | 일부 | 브라우저 URL 로딩만 사용. 원본의 보류 커버 저장소·캐시 관리와 동등하지 않음 | P2: 다량 파일 처리 필요에 따라 설계 |

원본 근거: [O-GUI] `CoverStore`, `apply_cover_to_all()`, `_set_cover_from_file()`; [O-PIPELINE] `fetch_cover()`; [O-TAGS] `read_cover()`, `prepare_cover()`, 포맷별 쓰기 함수.

## 6. 가사

| ID | 기능 | 원본 구현 | NAS 상태 | NAS 차이점·코드 근거 | 우선순위·개선 방향 |
| --- | --- | --- | --- | --- | --- |
| L01 | 옵션으로 가사 조회 활성화 | 기본 꺼짐, 저장 시 필요할 때 조회 | 일부 | [N-LYRICS]/[N-SCAN] 스캔 당시 옵션과 첫 후보로 조회. 저장 시 최종 태그로 다시 찾지 않음 | P1: 저장 시 최종 제목·가수 기준 조회 |
| L02 | LRCLIB 조회 | 조건 검색·키워드 검색 두 결과를 함께 판단 | 일부 | `/api/get` 단일 응답만 사용 | P1: 원본 검색·검증 경로 적용 |
| L03 | 제목·아티스트 일치 검사 | 정규화와 유사도 기준, 합동 크레딧 일부 허용 | 일부 | 요청에 제목·가수를 넣지만 반환 정보의 독립 검증은 없음 | P1: 반환 곡 정보 검증 |
| L04 | 버전·반주 구분 | 반주·Off Vocal·Karaoke·TV/Short 버전 구분과 다국어 표현 처리 | 일부 | 일부 영문 문자열을 `artist+title`에서 단순 검사. TV/Short 및 양쪽 버전 일치 검사 없음 | P1: 버전 플래그·반주 판별 이식 |
| L05 | 재생시간 차이 제한 | ±3초 검증 | 정상 | [N-LYRICS] 응답 길이와 파일 길이 차이가 3초 초과이면 거부 | 유지: 숫자 타입·길이 없는 파일 등 경계값 보강 |
| L06 | 가사 종료 시각 검증 | 동기 가사 마지막 시각이 곡 길이+허용 범위 이내인지 확인 | 미구현 | NAS는 `syncedLyrics` 시각을 검사하지 않음 | P1: 잘못 등록된 풀버전 가사 차단 |
| L07 | 일반 가사만 기록 | 일반 가사 또는 동기 가사에서 시각을 제거한 텍스트 | 일부 | `plainLyrics`만 반환. 시각 제거 대체 경로·제어 문자 정리·최소/최대 길이 검사 없음 | P1: 안전한 텍스트 정제 |
| L08 | 복수 기록 비교·중복 제거·충돌 거부 | 동일 복제 기록을 한 출처로 세고 내용 일치 집단 판단 | 미구현 | 단일 기록을 사용해 교차 검증 불가 | P1: 원본 합의 검증 적용 |
| L09 | 원문·로마자 가사 선택 | 일본어 등 원문 기록이 있으면 로마자 사본을 제외해 판단 | 미구현 | 해당 로직 없음 | P2: 원본 우선 규칙 이식 |
| L10 | 단일 가사의 과도한 글자 수 차단 | 대조 자료 없는 가사가 초당 12글자 초과이면 거부 | 미구현 | 해당 로직 없음 | P1: 오등록 가사 방어 |
| L11 | 기존 가사 읽기·보호 | USLT/LYRICS/UNSYNCEDLYRICS/©lyr 읽기, 실제 가사는 유지 | 미구현 | [N-READ] 가사를 읽지 않으며 [N-WRITE]는 기존 가사 유무를 확인하지 않음 | **P0**: 기존 가사 덮어쓰기 방지 |
| L12 | 플레이어 표시만 있는 가사를 빈칸으로 취급 | `[COWON S9]`, `[3 LINES]` 등을 식별하고 복원 가능하게 보존 | 미구현 | 기본 실행 파일에는 marker 판별 없음. 변형본에 일부 코드가 있어도 현재 기능이 아님 | P1: 가사 읽기·보호·백업과 함께 적용 |
| L13 | MP3 가사 저장 | `USLT`, 언어 `und` 기록 | 미구현 | [N-WRITE] Easy 인터페이스 `lyrics` 키 사용. 실제 NAS EasyID3 지원 키에 없음; 예외 무시 | **P0**: 형식별 올바른 쓰기와 실패 보고 |
| L14 | M4A 가사 저장 | `©lyr` 기록 | 미구현 | 실제 NAS EasyMP4 쓰기 키에 `lyrics` 없음; 예외 무시 | **P0**: MP4 원시 태그 매핑 및 오류 보고 |
| L15 | FLAC·OGG 가사 저장 | LYRICS 기록 및 기존 가사 보호 | 일부 | `audio_easy['lyrics']` 경로는 있으나 기존 가사 보호 없음. 실파일 쓰기 미시험, 현재 마운트는 읽기 전용 | **P0**: 보호 조건과 포맷별 검증 |
| L16 | 가사 내용 보기·상태 표시 | 기존/추가 가사 보기, found/none/busy/conflict/no_lyrics 등 구분 | 일부 | [N-SELECT] 검색된 가사 유무·줄 수만 표시. 내용 보기 및 상세 상태 없음 | P2: 기존/검색 가사 구분·상태 전달 |
| L17 | 서버 혼잡 시 재시도·연속 실패 제한 | 네트워크 재시도, 저장 배치 재시도, 5곡 연속 busy 시 중단 | 미구현 | [N-LYRICS] 모든 실패를 `None`으로 처리 | P1: busy 구분·제한·재시도 |
| L18 | 재저장 시 필요한 가사 재조회 | busy 등 재시도 가능한 상태면 다시 검색 | 미구현 | [N-SAVE] 스캔 결과 `r.lyrics`만 재사용 | P1: 저장 시 가사 상태에 따른 재검색 |
| L19 | 가사만 필요했으나 못 찾으면 파일 유지 | 원본 `_save_job()`은 태그 변경도 없으면 쓰지 않음 | 미구현 | [N-SAVE] 변경 여부 판단 없이 후보가 있으면 태그 쓰기 시도 | **P0**: 무변경 파일 쓰기 방지 |
| L20 | 가사 이용 주의·첫 활성화 안내 | 원본 가사 옵션 활성화 시 안내와 재열람 | 미구현 | 현재 실행 화면에는 해당 동작 없음 | P3: 필요 시 안내 복구 |

원본 근거: [O-LYRICS] 전반, [O-GUI] `lyrics_wanted()`, `_save_job()`, `view_lyrics()`; [O-TAGS] `_read_lyrics()`, `_set_lyrics()`.

### Mutagen 키 확인 결과

NAS 컨테이너에서 설치된 라이브러리의 키 목록과 `EasyMP4Tags.__setitem__()`를 읽기 전용으로 확인했다.

- `EasyID3.valid_keys`에 `lyrics`가 없다.
- `EasyMP4Tags.Set`에 `lyrics`가 없다. 지원 키가 없으면 `EasyMP4KeyError`를 발생시킨다.
- NAS 코드는 예외를 `except: pass`로 무시한 뒤 다른 태그 저장을 계속한다.
- 따라서 화면의 ‘가사 있음’은 **검색 결과가 있다는 의미**이며 MP3/M4A에 실제 기록됐다는 증거가 아니다.

## 7. 백업·되돌리기·파일 안전성

| ID | 기능 | 원본 구현 | NAS 상태 | NAS 차이점·코드 근거 | 우선순위·개선 방향 |
| --- | --- | --- | --- | --- | --- |
| B01 | 저장 전 원본 기록 | `.tagbak.json`에 기본 태그·식별자·가사·표지·레이아웃·SHA256 보관 | 일부 | [N-WRITE] 기본 태그/길이 JSON만 보관 | **P0**: 원본 수준 복원 가능 정보 확보 |
| B02 | 최초 백업을 원본으로 유지 | 기존 백업이 있으면 검증하고 재사용 | 미구현 | 매 저장 시 `write_text()`로 덮어씀 | **P0**: 최초 원본 보존 |
| B03 | 깨진 백업 시 저장 중단 | `BrokenBackup`으로 저장 차단 | 미구현 | 백업 생성 오류를 무시하고 쓰기 계속 시도 | **P0**: 백업 실패를 저장 차단 조건으로 처리 |
| B04 | 백업 원자적 기록 | 임시 파일 작성 후 교체 | 미구현 | [N-WRITE] JSON 직접 쓰기, 중간 실패 보호 없음 | **P0**: 원자적 저장·검증 |
| B05 | `/data/backups` 추가 보관 | 원본의 별도 중앙 보관 기능과는 다른 NAS 추가 기능 | 일부 | 파일명만 키로 사용해 서로 다른 폴더의 동명 파일끼리 충돌 가능 | **P0**: 상대 경로 또는 고유 식별자 사용 |
| B06 | 읽기 전용 음악 폴더에서도 중앙 백업 처리 | 원본은 쓰기 권한 문제를 명확히 보고 | 일부 | sidecar와 중앙 기록이 같은 try 안에 있어 sidecar 쓰기 실패 시 중앙 기록도 건너뜀 | **P0**: 권한·백업 실패를 정확하게 보고; 마운트 변경은 별도 승인 대상 |
| B07 | 바이트 단위 원본 복원 | 비오디오 영역과 현재 오디오를 재구성하고 SHA256 일치 시 원자 복원 | 미구현 | NAS 백업에는 레이아웃·원본 SHA256이 없고 복원 코드도 없음 | **P0**: 복원 포맷과 검증 구현 |
| B08 | 바이트 복원 불가 시 태그 값 복원 | 원본은 태그·표지·식별자·가사 복원으로 대체 가능 | 미구현 | [N-REVERT] JSON을 읽고 경로 반환만 함 | **P0**: 실제 파일 복원과 결과 구분 |
| B09 | 화면에서 되돌리기 실행 | 원본 `undo_current()`가 실제 restore 호출 | 미구현 | [N-RESET] 입력칸 제목·가수·앨범만 되돌림. `/api/revert`도 호출하지 않음 | **P0**: 편집 취소와 파일 복원을 명확히 구분 |
| B10 | 커버·가사·식별자까지 되돌리기 | 원본 백업/복원 경로가 포함 | 미구현 | 저장된 백업 정보부터 부족 | **P0**: 통합 복원·형식별 회귀 시험 |
| B11 | 이름 변경 후 백업 발견 및 복원 | 음악 파일과 백업을 함께 이동 | 미구현 | [N-WRITE] 백업 이름·작업 경로 갱신 누락 | **P0**: 이름 변경과 복원 경로 일관성 |
| B12 | 저장 전 음악 파일을 변경하지 않음 | 원본의 명시적 원칙 | 정상 | [N-SCAN] 검색·태그 읽기만 수행. `/data/jobs.json` 기록은 음악 파일 변경과 별개 | 유지 |

원본 근거: [O-TAGS] `make_backup()`, `load_backup()`, `restore_backup()`, `_atomic_write()`, `rename_file()`; [O-PIPELINE] `save_file()`; [O-GUI] `undo_current()`.

**원본의 바이트 복원도 무조건 보장되는 것은 아니다.** 레이아웃을 이해하고 재구성한 파일의 SHA256이 맞을 때 정확 복원하며, 불가능하면 태그 값 복원으로 대체한다. NAS에는 이 두 복원 경로가 모두 없다.

**배포 백업과 음악 태그 백업은 다른 기능이다.** `deploy-backups/`의 코드·Compose 스냅샷은 배포 이전 파일 보관용이며, 음악 파일의 태그·커버·가사를 복구하는 `.tagbak.json` 기능을 대신하지 않는다.

## 8. 설정·실행 방식·NAS 추가 기능

| ID | 기능 | 원본 구현/비교 기준 | NAS 상태 | NAS 차이점·코드 근거 | 우선순위·개선 방향 |
| --- | --- | --- | --- | --- | --- |
| E01 | CLI 입력·자동 처리·음향 검색·undo | 원본 `main.py`의 `--auto`, `--sound`, `--undo`, `--lyrics`, `--rename` 등 | 미구현 | NAS는 웹 API 방식. 배포 스크립트는 음악 처리 CLI가 아님 | P3: NAS용 CLI 필요 여부 결정 |
| E02 | 언어 선택·OS 언어 기반 초기값 | 원본 한국어·영어·중국어·일본어 | 미구현 | 현재 화면과 문구는 한국어 고정 | P3: 다국어 필요 시 구현 |
| E03 | 사용자 설정 보관 | 원본 `prefs.py`/`settings.json`: 국가·가사·이름 변경·키·fpcalc·표지 크기 등 | 미구현 | NAS는 환경변수와 작업별 옵션만 있음. 동등한 설정 저장/검증 체계 없음 | P2: NAS에 필요한 설정만 설계 |
| E04 | 새 버전 확인·알림·다음에·비활성화 | 원본 하루 한 번 백그라운드 확인 | 미구현 | 해당 로직 없음. 원본도 자동 다운로드/자동 설치는 하지 않음 | P3: Docker 운영에 맞는 알림 필요 여부 결정 |
| E05 | 음악 파일 미업로드 원칙 | 원본은 검색어/지문만 외부 전송 | 정상 | NAS 현재 외부 호출도 검색어·메타데이터·커버/가사 조회 중심. 음악 업로드 로직 없음 | 유지: 지문 구현 후에도 동일 원칙 유지 |
| E06 | NAS 계층형 폴더 선택·폴더 검색 | 원본과 다른 입력 방식의 NAS 추가 기능 | 정상 | [N-FOLDERS]/[N-TREE] 목록 자동 로드, 계층 펼침/접기, 검색, 선택 후 열린 상태 유지 | 유지 |
| E07 | 브라우저를 닫아도 스캔 계속 | NAS 추가 기능 | 정상 | FastAPI BackgroundTasks로 서버 측 작업 실행 | 유지: 서버 재시작 시에는 자동 계속 실행이 아님 |
| E08 | 진행률·결과 저장·재접속 조회 | NAS 추가 기능 | 일부 | [N-JOBS]/[N-POLL] `jobs.json`과 조회 API 존재. 원자 저장·동시 접근 제어 없음, 저장 오류 무시 | P2: 상태 저장 신뢰성 개선 |
| E09 | 중지·이어하기 | NAS 추가 기능 | 일부 | 결과 개수부터 재개하며, 계산한 `existing_paths`는 사용하지 않음. 파일 목록 변경 시 누락·중복 가능 | P2: 경로/파일 식별자 기반 재개 |
| E10 | 서버 재시작 후 중단 상태 복구 | NAS 추가 기능 | 일부 | `scanning/queued`를 `interrupted`로 바꿈. `cancelling` 복구는 누락 | P2: 모든 비종료 상태 정규화 |
| E11 | 중복 스캔 방지 | NAS 추가 기능 | 일부 | [N-ACTIVE]/[N-START] 활성 검사에서 `cancelling` 제외, `force`는 우회 가능 | P2: 상태·취소 완료를 포함한 동시 작업 관리 |
| E12 | 파일 목록 필터·체크 선택 | NAS 추가 기능 | 정상 | [N-FILTER] 목록 검색·체크 상태 처리. 단, 저장 범위 문제 S10/S11은 별도 결함 | 유지 |
| E13 | 작업 삭제 | NAS 추가 기능 | 일부 | [N-DELETE] DELETE API 존재. 화면의 ‘중지/삭제’ 흐름은 cancel만 호출 | P2: 실제 삭제 명령 연결 및 문구 일치 |
| E14 | 파일별 작업·후보 상태 일관성 | 원본은 파일별 `FileState` 유지 | 일부 | [N-POLL] 활성/최신 작업으로 자동 전환하며 결과 길이만 비교. 같은 개수의 다른 작업·수동 열람 상태와 어긋날 수 있음 | P1: job ID와 결과 버전을 기준으로 동기화 |
| E15 | NAS 자동 배포 | 원본 음악 처리 기능 밖의 NAS 운영 기능 | 정상 | [N-DEPLOY] 변경 파일 비교·백업·SCP·빌드·기존 설정 검증·v6 재생성·HTTP/API 확인. 실제 배포 성공 이력 있음 | 유지: 업로드 허용 파일은 현재 두 개, 다른 파일 변경 시 범위 검토 |
| E16 | 음악 폴더 읽기 전용 보호 | 현재 NAS의 의도된 운영 조건 | 정상 | Docker inspect에서 `/music`의 `RW=false` 확인. 저장 가능 여부와 별개로 보호는 동작 중 | 유지: 변경은 별도 명시적 요청 필요 |

원본 근거: [O-MAIN], [O-PREFS], [O-I18N], [O-UPDATE], [O-README]. NAS 추가 기능은 원본과 동일 기능이라는 의미가 아니라 별도 운영 기능으로 기록했다.

### 원본도 제공하지 않는 기능

아래 항목은 원본 README의 의도적 범위 밖이다. NAS가 원본 기능을 누락한 것으로 집계하지 않는다.

- 음악 다운로드·변환·재생.
- 스트리밍 서비스 계정 연동.
- 공식 API 없는 국내 음악 서비스 스크래핑.
- `.lrc` 파일 생성.
- 새 버전 자동 다운로드·자동 설치.
- 가수/앨범별 폴더 재배치·중복 정리: 별도 프로젝트 `music-folder-organizer`의 기능이며 이 비교의 이식 대상이 아니다.

## 9. 개선 실행 순서

이 절은 향후 개선 계획이며, 이번 문서 작성으로 구현하거나 배포한 내용이 아니다.

1. **P0 — 저장 계약과 데이터 보호:** 후보·수동 입력·필드 마스크를 서버 요청에 포함하고 검증한다. 자동 선택 90점/유효 검색어 조건, 명시적 선택 여부, 실제 저장 범위를 구분한다. 무변경·실패·부분 성공 상태를 정확히 보고한다.
2. **P0 — 복원 가능한 백업:** 최초 백업 보존, 원자 기록, 무결성 검사, 실패 시 저장 차단을 구현한다. 커버·가사·식별자·원본 레이아웃을 보관하고 실제 복원과 형식별 회귀 검증을 완성한다. 이름 변경과 백업 이동도 함께 처리한다.
3. **P0/P1 — 형식별 저장:** MP3/FLAC/M4A/OGG의 기본 7개 태그·커버·가사 쓰기를 명시적으로 구현한다. 기존 가사·표지 보호와 오류 보고를 먼저 확정한다.
4. **P1 — 검색 정확도:** iTunes US 폴백, MB 발매 선정, 후보 병합·길이 점수, 일반적 파일명 차단, 재검색과 AcoustID를 연결한다.
5. **P1 — 가사 정확도:** 최종 태그 기준 저장 시 조회, 곡/버전/길이/종료시각/다중 기록 검증, 혼잡 재시도와 실패 제한을 적용한다.
6. **P2 — 작업·파일 관리:** 경로 기반 이어하기, job ID 기반 결과 갱신, 설정 저장, 식별자·정렬 이름, 파일명 변경과 이미지 입력·일괄 적용을 보강한다.
7. **P3 — 선택적 이식:** CLI·다국어·업데이트 알림은 NAS 운영상 필요에 따라 결정한다.

검증은 복사한 음원과 격리된 테스트 경로에서 수행해야 한다. 현재 음악 마운트를 쓰기 가능하게 바꾸는 것은 이 계획에 포함하지 않는다. 저장 시험에 앞서 원본 유지·백업·오류 보고를 검증하고, 원본 파일과 복원 파일의 SHA256을 대조하는 회귀 시험이 필요하다.

## 10. 코드 근거 색인

### 원본 GitHub 소스

다음 링크는 모두 같은 커밋으로 고정되어 있다.

- [O-README]: 전체 기능 설명과 의도적 제외 범위.
- [O-TAGS]: `read_file()`, `_read_lyrics()`, `_set_lyrics()`, `write_file()`, `prepare_cover()`, `make_backup()`, `restore_backup()`, `rename_file()`.
- [O-PIPELINE]: `auto_pick()`, `apply_candidate()`, `search_text()`, `search_sound()`, `fetch_cover()`, `find_lyrics()`, `save_file()`.
- [O-MATCH]: `guess_from_filename()`, `is_generic_name()`, `score()`, `merge()`, `rank()`.
- [O-GUI]: `FileState`, `apply_selected()`, `_save_job()`, `apply_cover_to_all()`, `undo_current()`.
- [O-ITUNES]: `search()`, `album_artwork()`, 국가 폴백.
- [O-MB]: `build_query()`, `_pick_release()`, `candidate_from_recording()`.
- [O-ACOUSTID]: `find_fpcalc()`, `fingerprint()`, `lookup()`.
- [O-LYRICS]: 곡·버전·길이·텍스트 합의 검사, `marker_only()`, `pick()`, `find()`.
- [O-NET]: 속도 제한·취소·429/503 재시도·응답 크기 제한.
- [O-MAIN]: CLI 옵션과 검색·저장·되돌리기 연결.
- [O-PREFS], [O-I18N], [O-UPDATE]: 사용자 설정·언어·업데이트 알림.

### NAS v6 실행 소스

| 참조 | 파일·함수·작성 당시 줄 | 확인 내용 |
| --- | --- | --- |
| [N-PARSE] | `app/main.py` L42–47, `parse_filename()` | 단순 파일명 분리 |
| [N-IT] | `app/main.py` L49–76, `search_itunes()` | KR 고정·점수·후보 필드 |
| [N-MB] | `app/main.py` L78–107, `search_musicbrainz()` | 첫 크레딧/발매 사용 |
| [N-LYRICS] | `app/main.py` L109–126, `search_lrclib()` | 단일 조회와 제한적 검증 |
| [N-READ] | `app/main.py` L128–148, `read_tags()` | 커버·가사·식별자 미반환 |
| [N-WRITE] | `app/main.py` L150–222, `write_tags()` | 백업·텍스트·가사·MP3 표지·이름 변경 |
| [N-SCAN] | `app/main.py` L224–324, `scan_job()` | 탐색·후보·가사·자동 선택 표식·이어하기 |
| [N-OPTIONS] | `app/main.py` L326–332, `ScanRequest` | 사용하지 않는 지문 옵션 포함 |
| [N-ACTIVE] | `app/main.py` L334–338, `get_active_job()` | 활성 상태 검사 |
| [N-FOLDERS] | `app/main.py` L340–352, `list_folders()` | 폴더 API |
| [N-START] | `app/main.py` L355–385, `start_scan()` | 경로·중복 스캔 검증 |
| [N-JOBS] | `app/main.py` L22–40, L387–450 | jobs 저장·조회·취소·재개 |
| [N-DELETE] | `app/main.py` L414–423, `delete_job()` | 작업 삭제 API |
| [N-SAVE] | `app/main.py` L452–480, `save_job()` | 경로만 받아 서버 best 저장 |
| [N-REVERT] | `app/main.py` L482–492, `revert_file()` | JSON 읽기만 하고 복원하지 않음 |
| [N-UI] | `app/static/index.html` 전반 | 실제 실행 UI와 JavaScript |
| [N-APPLY] | `app/static/index.html` L123 | 미정의 `applySelectedCandidate()` 호출 |
| [N-TREE] | `app/static/index.html` L152–206 | 폴더 트리·선택·검색 |
| [N-SCAN-UI] | `app/static/index.html` L207–213 | 스캔 옵션 구성, rename 고정 false |
| [N-POLL] | `app/static/index.html` L214–245 | 작업/결과 자동 갱신 |
| [N-FILTER] | `app/static/index.html` L246–252 | 파일 필터·체크 |
| [N-SELECT] | `app/static/index.html` L253–260 | 현재 태그·빈 기존 커버·가사 상태 |
| [N-CAND] | `app/static/index.html` L261–290 | 후보 클릭과 로컬 r.best 변경 |
| [N-UI-SAVE] | `app/static/index.html` L291–293 | 체크·저장 요청의 누락된 값 |
| [N-RESET] | `app/static/index.html` L294 | 입력칸 일부만 되돌림 |
| [N-MANUAL] | `app/static/index.html` L295 | 빈 재검색 함수 |
| [N-DEPS] | `requirements.txt`, `Dockerfile` | 라이브러리·fpcalc 설치와 실제 호출 구분 |
| [N-DEPLOY] | `deploy-nas.ps1`, `DEPLOYMENT.md` | 코드 배포 및 컨테이너 검증, 음악 백업과 별개 |

## 11. 작업 범위 기록

앞선 비교 분석은 GitHub 소스와 Windows 소스 읽기, NAS의 마운트·파일 해시·Mutagen 지원 키에 대한 읽기 전용 조회만 수행했다. 이 파일 작성 작업은 `FEATURE_COMPARISON.md` 문서만 추가한다. 기존 코드·CSS·설정·음악 파일을 수정하지 않으며 NAS 파일 전송·Docker 빌드·컨테이너 재배포도 실행하지 않는다.

[O-README]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/README.md
[O-TAGS]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/tags.py
[O-PIPELINE]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/pipeline.py
[O-MATCH]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/match.py
[O-GUI]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/gui.py
[O-ITUNES]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/search_itunes.py
[O-MB]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/search_mb.py
[O-ACOUSTID]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/search_acoustid.py
[O-LYRICS]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/search_lyrics.py
[O-NET]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/net.py
[O-MAIN]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/main.py
[O-PREFS]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/prefs.py
[O-I18N]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/i18n.py
[O-UPDATE]: https://github.com/microhan1/music-tag-filler/blob/8996e2daa74c787395ebbf3f9d871b1484f4aafe/update_check.py
[N-PARSE]: app/main.py#L42
[N-IT]: app/main.py#L49
[N-MB]: app/main.py#L78
[N-LYRICS]: app/main.py#L109
[N-READ]: app/main.py#L128
[N-WRITE]: app/main.py#L150
[N-SCAN]: app/main.py#L224
[N-OPTIONS]: app/main.py#L326
[N-ACTIVE]: app/main.py#L334
[N-FOLDERS]: app/main.py#L340
[N-START]: app/main.py#L355
[N-JOBS]: app/main.py#L22
[N-DELETE]: app/main.py#L414
[N-SAVE]: app/main.py#L452
[N-REVERT]: app/main.py#L482
[N-UI]: app/static/index.html
[N-APPLY]: app/static/index.html#L123
[N-TREE]: app/static/index.html#L152
[N-SCAN-UI]: app/static/index.html#L207
[N-POLL]: app/static/index.html#L214
[N-FILTER]: app/static/index.html#L246
[N-SELECT]: app/static/index.html#L253
[N-CAND]: app/static/index.html#L261
[N-UI-SAVE]: app/static/index.html#L291
[N-RESET]: app/static/index.html#L294
[N-MANUAL]: app/static/index.html#L295
[N-DEPS]: requirements.txt
[N-DEPLOY]: deploy-nas.ps1
