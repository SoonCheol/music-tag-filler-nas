# UI JavaScript 기능별 위치

모든 경로는 `app/static/js/` 기준이다. 전역 상태·DOM ID·함수 이름을 유지하는 일반 스크립트이며 ES module이 아니다.

| 파일 | 책임 | 주요 진입점 |
| --- | --- | --- |
| `search-list.js` | 검색·스캔, 작업 폴링, 폴더·목록·필터·정렬·선택 | `startScan`, `pollJobs`, `manualSearch`, `renderFileList`, `selectFile` |
| `candidate-media.js` | 후보 표, 커버·썸네일·오디오, 이미지/가사 공유 동시 실행 예산 | `renderCandidates`, `requestCandidateCover`, `pumpCandidateMedia`, `toggleAudio` |
| `lyrics.js` | 후보·저장 가사 조회, 캐시, 초안 보호, 표시 | `requestCandidateLyrics`, `applySelectedLyrics`, `searchLyricsForCurrent`, `renderLyricsPanels` |
| `tag-editor.js` | 태그 초안·보호·미리보기·저장·복원·파일명 변경 | `ensureDraft`, `applyCandidate`, `submitSave`, `beginFilenameEdit`, `applyPathChange` |
| `options-ui.js` | 설정·옵션창, 확인창, 툴팁 | `loadPreferences`, `openSaveOptions`, `confirmAction`, `showButtonTooltip` |
| `app.js` | 공유 상태, `$`·`api`·`esc`, 이벤트 등록과 초기 실행 | 전역 선언 및 기존 순서의 초기화 |

## 로딩과 상태 의존성

`index.html`은 위의 기능 파일 5개를 먼저 로드하고 `app.js`를 마지막에 로드한다.
기능 파일에는 함수 선언만 있다. 로드 시 DOM·공유 상태를 읽거나 다른 파일을 실행하지 않으므로 파일 간 import 및 순환 로딩 의존성이 없다.
함수는 실행 시 같은 전역 상태를 참조한다. ES module, async, defer, 동적 import로 변경하면 기존 실행 계약이 달라지므로 이번 구조에 추가하지 않는다.

원래 최상위 함수 141개와 중첩 함수 4개의 본문을 그대로 옮겼다. 상태 선언과 이벤트 등록을 포함한 나머지 최상위 구문 79개는 `app.js`에서 원래 순서를 유지한다.
공유 상태를 재배치하거나 상태 객체로 감싸지 않았다. 마지막 호출 순서는 `renderFileList()` → `loadPreferences()` → `loadFolders()` → `pollJobs()` → `pollSaveTasks()`다.

- 목록/선택: `currentJobId`, `allJobs`, `currentResults`, `filteredResults`, `editingResult`를 공유한다. 목록 선택이 편집·미디어·가사 화면을 갱신한다.
- 편집/저장: `tagFields`, `commonTagFields`, `commonSaveCover`, `commonSaveLyrics`, `draftJobs`, `saving`, `searching`을 공유한다. 가사의 최종 검색 기준도 편집 값과 보호 규칙을 따른다.
- 미디어/가사: 커버·가사 큐와 실행 수는 `app.js`에서 초기화한다. `pumpCandidateMedia`가 총 동시 실행 2개와 사용자 요청 우선순위를 유지하며 `lyrics.js`의 작업도 실행한다.
- 파일명 변경: 목록 경로·재생 상태·가사 캐시를 함께 갱신한다. `tag-editor.js`의 경로 변경 함수가 기존 미디어·가사 함수를 호출한다.
- 설정: 옵션 확인 후 편집 미리보기를 갱신한다. 옵션 기억을 선택한 경우에만 기존 설정 저장 흐름을 사용한다.

## 검증·복구

기존 UI 테스트는 HTML의 스크립트 목록을 읽고 각 파일을 브라우저와 같은 전역 컨텍스트에 순차 실행한다. 기능 파일만 로드할 때 DOM·공유 상태 접근이 없는지도 검사한다.
복구 시 `index.html`, `css/style.css`, JavaScript 6개 파일을 같은 버전으로 함께 복구한다.
배포 허용 목록은 JavaScript 6개를 모두 포함한다. Dockerfile의 `COPY app/ ./app/` 및 `.dockerignore`의 `!app/**`는 새 파일을 이미 포함한다.
