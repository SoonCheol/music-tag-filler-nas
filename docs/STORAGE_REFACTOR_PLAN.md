# #013 저장·복원·태그 처리 구조 개선 계획

**상태: 지정 범위의 읽기 전용 정적 분석 완료 — 2026-10-26. 구현·실행 검증은 미수행.**

분석 기준은 현재 작업 공간의 `work/project` 소스다. `git status --short`는 Git 저장소가 아니라는 오류를 반환했다. 따라서 HEAD, 기존 미커밋 변경, 운영 배포본과의 동일성은 확인되지 않았다. 다음 구현 전에 실제 Git 작업본과 이 소스의 관련 파일을 대조해야 한다. 문서의 함수·행 번호는 이 소스 기준이며 운영 실측이 아니다.

이번 변경은 이 문서뿐이다. 코드/테스트 수정, 테스트 실행, 모듈 import 실행, NAS 접속·배포, commit/push, 실제 음악·운영 data 읽기/변경은 하지 않았다. 관련 문서에 기재된 과거 통과 결과를 이번 검증 결과로 사용하지 않았다.

## 1. 핵심 결론과 탐색 지도

보호 검사를 줄이는 방식보다 **입출력 기초 → 백업 저장소 → 오디오 검증 → 저장 정책/검증 → 요청 조정 → 포맷 구현** 순으로 책임을 분리한다. 파일명 변경 경로 통합과 내구성 강화는 동작 변경이므로 기계적 분리와 별도 작업으로 취급한다.

| 목적 | 현재 진입점/근거 |
| --- | --- |
| 요청 범위, 잠금, 배치 결과 | `app/main.py:919 save_job`, `:945 perform_save_job` |
| 후보·체크·ID·커버·가사 정책 | `app/main.py:768 save_one`, `:624 selected_lyrics` |
| 음악 저장 트랜잭션 | `app/storage.py:208 save` |
| 최초 백업/검증/실제 바이트 복원 | `storage.py:144 ensure_backup`, `:106 _verify_backup`, `:339 restore` |
| 직접 rename/전진 복구 | `app/rename_service.py:176 rename`, `:111 finish`, `:154 recover` |
| LRC 생성/전진 복구 | `app/lyric_assets.py:24 begin`, `:38 finish`, `:54 recover` |
| 포맷 기록/미선택 ID3 보호 | `app/upstream/tags.py:495 write_file`, `:573 id3_preserved_frames` |
| 오디오 영역 비교 | `tags.py:919 _layout`, `:953 _audio_bytes` |
| 시작 시 복구 순서 | `main.py:1252 recover_filename_changes` |

`storage.save` 약 130행은 정책 계산·백업·임시 파일·검증·교체·LRC·이름·결과 보고를 동시에 맡는다. `main.save_one` 약 120행도 후보 신뢰 검증과 네트워크 자산 취득 및 저장 결과 가공이 섞여 있다. `tags.py`는 약 1,000행에 모델·포맷 I/O·커버 가공·이름·옛 백업/복원·바이트 파서를 함께 가진다. 행 수 자체보다 변경 이유가 서로 다른 책임의 혼합이 문제다.

## 2. 실제 저장·복원 흐름

### 2.1 요청에서 저장까지

1. `save_job`은 복구 차단 상태 및 이름 변경 예약을 검사하고 별도 `save_tasks_lock` 아래 진행 항목을 만든다.
2. `perform_save_job`은 배치 전체에서 동일 `storage.OPERATION_LOCK`(RLock)을 보유한다. 작업 존재/진행 상태, paths/items 일치·중복, 작업 소속, current 한 곡, selected/all의 checked_paths 및 자동선택 상태를 검사한다.
3. `save_one`은 루트 밖/심볼릭 링크/지원 포맷 검사와 전체 파일 SHA256 리비전 검사를 한다. 체크 필드·값, 자동 후보 90점 경계 및 후보 ID, 수동 후보 소속을 확인한다. 자동 요청값은 브라우저 값 대신 검증된 후보에서 만든다.
4. 최종 텍스트와 후보의 일치에 따라 ID 반영 범위를 제한한다. 커버/가사는 옵션·빈 항목 정책·검색 토큰의 파일/작업/리비전/질의/후보 연결을 검사한다. 쓰기가 예상되면 네트워크 조회 전에 권한을 검사한다.
5. 커버 취득/가공, 필요한 구 API 가사 조회, 확인된 가사 선택을 거쳐 `storage.save`를 부른다. 편집된 일반 가사에 기존 타임스탬프를 재사용하지 않는다.
6. 파일별 saved/skipped/partial/failed와 현재 경로/리비전을 작업 메모리에 반영하고, 마지막 `save_jobs` 오류는 `state_error`로 별도 보고한다. partial은 saved 합계에도 포함되는 기존 응답 계약이다.

현재 save의 네트워크 조회도 배치 OPERATION_LOCK 안에 있다. 읽기 진행률은 별도 잠금이므로 조회 가능하다. 잠금 범위를 줄이는 최적화는 이번 분리 계획의 초기 단계에 포함하지 않는다.

### 2.2 최초 백업

- `save`는 리비전 재검사와 실제 현재 태그 읽기 후 최종 값을 계산한다. 완전 무변경이면 백업·쓰기·mtime 변경 없이 종료한다.
- 변경이 있으면 쓰기 권한 검사 후 `ensure_backup`을 호출한다. 기존 sidecar가 있으면 매번 검증하며 덮어쓰지 않는다. 옛 중앙 백업만 있으면 새 최초 원본 생성으로 우회하지 않고 차단한다.
- 신규 백업 ID는 음악 상대 경로 문자열의 SHA256이다. 중앙 `.backup-*` 임시 디렉터리에 음악을 복사하고 복사본/현재 음악이 expected SHA256과 같은지 확인한다.
- 복사본에 `tags.make_backup`을 적용해 태그/레이아웃을 얻고 `nas_backup_id`를 추가한다. `original.bin`, `tags.json`, version 2 `manifest.json`, `manifest.sha256`을 만든다. 각 파일 fsync 후 중앙 디렉터리를 공개하고 sidecar를 `_new_file`로 신규 생성한다.
- `_new_file`은 같은 디렉터리 임시 파일 쓰기/flush/fsync 후 hard link로 공개한다. 대상이 이미 있으면 실패하며 최초 백업을 교체하지 않는다.
- `_verify_backup`은 ID 형식, manifest 해시/version, 상대 경로 또는 alias checksum, 원본 크기/전체 해시, 중앙 tags 해시와 sidecar 바이트 일치, 레코드 메타데이터를 확인한다.
- 중앙 공개 후 sidecar만 실패했으면, 다음 실행에 중앙 백업을 검증하고 현재 파일이 최초 SHA256과 같은 경우에만 sidecar 재생성을 허용한다. 수정된 음악을 새 최초 원본으로 간주하지 않는다.

### 2.3 임시 기록·검증·교체

- 내용 변경 시 음악과 같은 폴더에 `.tagtxn-*`을 만들고 현재 음악을 복사한다. `tags.write_file`은 이 복사본만 수정한다.
- 다시 읽어 최종 7개 필드, ID, 커버, 일반/동기 가사를 비교한다. 비변경 커버/가사/SYLT도 보존 여부를 검사한다.
- MP3는 변경 대상 이외의 디코딩된 프레임 payload와 unknown_frames, ID3 버전까지 추가 비교한다. 이는 일반 태그 값 검사와 다른 보호다.
- 원본과 stage에서 포맷별 오디오 영역을 추출·비교한다. 원본 리비전을 다시 확인하고 stage의 mode를 원본에 맞춘 뒤 fsync한다.
- LRC가 필요하면 음악 before/after SHA256이 담긴 pending 저널을 먼저 공개한다. 그 다음 `os.replace(stage, path)`로 음악을 교체한다. finally에서 잔여 stage를 삭제한다.
- 교체 전 오류는 음악 원본을 유지한다. 이미 만든 유효 최초 백업은 남는다. **교체 후 오류에는 음악 전체를 자동 롤백하지 않는다.** 모든 실패가 “원본을 변경하지 않음”을 뜻하지 않는다.
- 일반 저장은 교체 후 `describe`로 상태를 읽지만 stage 전체 해시와 교체된 음악의 전체 해시를 별도로 비교하는 절차는 없다. restore의 최종 SHA256 검사와 구분한다.

### 2.4 LRC와 이름 변경

LRC는 create-only다. 대소문자/NFC 충돌, 링크, 기존 다른 내용은 거부하고 동일 내용이면 건너뛴다. `finish`는 음악이 after 해시인지 확인한 뒤 LRC를 신규 공개하고 complete 저널을 기록한다. 실패하면 한 번 더 시도하며 계속 실패하면 차단 상태를 남긴다. 시작 시 after이면 완료, before이면 aborted, 둘 다 아니면 차단한다. LRC만 생성하는 경우 before=after이며 after 분기가 우선한다.

| 경로 | 순서와 실패 처리 |
| --- | --- |
| 직접 rename 및 LRC 동반 자동 rename | pending 기록 → 음악 `renameat2(RENAME_NOREPLACE)` → sidecar 이동 → alias 생성/백업 검증 → LRC 이동 → 모든 관련 작업 경로 갱신/영속화 → complete. 실패 시 실제 경로·inode/device·SHA256으로 전진 복구; 옛 파일만 그대로면 aborted; 모호하면 차단 |
| LRC 없는 자동 rename | alias 신규 생성 → `tags.rename_file`의 sidecar `os.replace` → 음악 `os.replace`. 음악 이동 실패 시 sidecar 되돌리기 시도; 실패 위치를 RenameFailed에 담음. 지속 저널 없음 |

자동 이름 생성은 충돌 시 `(2)` 등 이름을 고르고, 직접 이름 변경은 지정 이름 충돌을 거부한다. 통합할 때 이 사용자 동작 차이는 보존해야 한다. LRC 자동 rename에서는 이미 저장된 음악 리비전으로 작업 행을 갱신하고 rename_service에 넘긴다.

시작 시 rename 복구 후 LRC 복구를 수행한다. 음악/LRC 완료 후 rename하는 순서와 연결되므로 무심코 역전하지 않는다. rename 저널의 상태·필드, 선택적 `lrc_sha`, backup alias와 작업 경로를 보존한다.

### 2.5 원본 복원

`revert_file`은 활동 등록/차단 검사와 OPERATION_LOCK 안에서 `storage.restore`를 호출한다. 요청 리비전 → 백업 검증 → 이미 원본이면 skipped → 쓰기 권한 → 읽은 original.bin 재해시 → 현재/원본 오디오 비교 → 현재 리비전 재검사 → `_replace_file` → 최종 전체 SHA256 확인 순서다. 작업 기록 저장 실패는 파일 복원과 분리 보고한다.

복원은 최초 음악 전체 바이트의 복원이다. 파일명은 현재 이름을 유지하고 별도 LRC는 삭제/교체하지 않는다. `tags.restore_backup`의 태그 수준 fallback과 다른 계약이다. NAS restore를 그 함수로 대체하면 안 된다. `upstream/pipeline.py:239 save_file`도 옛 직접 기록 경로이므로 NAS의 검증된 stage 저장을 그것으로 대체하지 않는다.

## 3. 의존성·중복·포맷 차이

### 3.1 private 의존성

| 소비자 | storage 비공개 함수 |
| --- | --- |
| `rename_service.write_record/finish/recover/rename` | `_json_bytes`, `_new_file`, `_replace_file`, `_verify_backup` |
| `lyric_assets.begin/finish/recover` | `_json_bytes`, `_new_file`, `_replace_file` |
| `job_store.load/save` | `_json_bytes`, `_replace_file` |
| `preferences.write` | `_replace_file` |

P0/P3/P5/P6 및 verify_nas_rw 소스도 private 검증/patch 지점에 의존한다. 이동 시 이름만 유지해도 patch가 실제 실행 경로에서 빠질 수 있다. 테스트가 의도한 실패를 실제로 주입했는지 확인해야 한다.

`storage → lyric_assets → storage`, `storage → rename_service → storage`, `lyric_assets → rename_service → storage` 의존성이 있다. storage의 지연 import가 초기 import 충돌을 피하지만 책임 순환을 해소하지는 않는다. job_store도 storage와 rename_service의 저수준 I/O를 끌어온다. storage는 tags의 `_layout/_audio_bytes`에도 직접 결합되어 있다.

최종 방향: 정책/트랜잭션 조정 모듈이 leaf 모듈인 파일 I/O·백업·오디오 검증·포맷 코덱을 호출하고, 저널 모듈은 leaf 기능에만 의존한다. `StorageError` 및 하나의 잠금 객체는 공통 계약 모듈에서 정의하고 기존 storage 이름으로 재노출한다. 새로운 RLock을 따로 만들지 않는다.

### 3.2 공통화 가능 범위와 보존할 차이

| 포맷 | 텍스트/ID/가사/커버 | 무결성·보존 특성 |
| --- | --- | --- |
| MP3 | ID3 프레임, TXXX/UFID/TSOP/TSO2, USLT/SYLT, APIC | v2.3 유지·나머지 v2.4, 다중값/정렬 프레임/unknown_frames 보호. ID3v2 앞부분 및 ID3v1 꼬리를 제외한 영역 비교 |
| FLAC | Vorbis comments, lyrics/기존 별칭 읽기, native Picture | 마지막 metadata block 뒤 오디오 비교. 새 커버는 기존 그림 집합 교체 |
| OGG Vorbis | FLAC과 텍스트/ID 공통, metadata_block_picture base64 | Vorbis 헤더 이후 페이지 sequence를 원본 기준으로 정규화하고 페이지를 재직렬화해 비교. raw 전체 바이트 비교로 대체 불가 |
| M4A/MP4 | ©nam 등 atom, trkn 숫자쌍, FreeForm IDs/soar/soaa, ©lyr, covr | 정확히 하나의 mdat payload 비교. mp4 확장자 일반 지원을 의미하지 않음; 현재 확장자는 m4a |

공통 부분은 모델, 선택 필드 집합, IDs 병합 규칙, None 보존 의미, 결과 검증의 호출 규약이다. Vorbis 필드/IDs 매핑은 이미 공유하므로 새 일반화 프레임워크로 다시 합칠 필요가 없다. 코덱은 포맷별 프레임/atom 및 저장 옵션을 소유해야 한다.

저수준 `_set_lyrics`의 빈 문자열은 삭제 의미지만 NAS `storage.save`는 빈 입력을 보존으로 바꾼다. 이 층별 계약을 하나로 바꾸지 않는다. 빈 커버도 API와 저수준 writer 양쪽에서 보존한다.

### 3.3 제거 대상이 아닌 반복 검사

- main 진입 리비전: 사용자가 확인한 대상; storage 진입/백업 중/교체 직전: 각 시간 구간의 경쟁 방어.
- describe 전후 해시: 읽는 동안의 변경 감지; 저장 리비전 검사와 별도.
- 백업 전체 검증, 복원용 bytes 재해시, 복원 후 해시: 각각 보관 무결성·사용 시점·출력 검증.
- 태그 재읽기, 미선택 ID3 프레임 비교, 오디오 영역 비교: 서로 다른 손실 탐지.
- API의 후보·옵션 검사와 storage의 기존 값 보존: 신뢰 경계가 다름.
- 커버 prepare 호출은 현재 main에서 요청 크기, storage에서 기본 크기로 재호출된다. 단순 중복으로 삭제하지 말고 1000 초과 옵션 등 결과를 먼저 고정해야 한다.

JSON 직렬화, 원자 파일 쓰기, alias 생성 규칙은 책임 이동 후보지만 create-only/replace/no-replace의 의미 차이는 유지한다. upstream의 `.part` 방식 옛 복원과 NAS의 fsync/전체 원본 방식은 동등한 중복이 아니다.

## 4. 기존 테스트의 보호 범위와 공백

아래는 테스트 소스의 assertion과 실패 주입을 확인한 결과다. 실행 통과나 테스트 수를 보고하는 것이 아니다.

| 관련 테스트 | 확인한 보호 |
| --- | --- |
| `test_p0_storage.py` | 4포맷 최초 sidecar 유지/정확 바이트 복원, 무변경·mtime, 백업 구성요소 손상, 백업/stage 실패, sidecar 재개, legacy 차단, 리비전/RO, 경로/후보/범위, 배치 부분 실패·state_error, 동시 HTTP 저장 |
| `test_p1_search.py` 관련 부분 | marker 가사 대체 후 4포맷 전체 바이트 복원 |
| `test_p2_workflow.py` 저장 관련 부분 | ID/체크/빈 값, 자동·수동·범위·커버 옵션, 충돌 자동 rename, 가사 4포맷/범위/체크 조합, 검색 토큰 바인딩·빈 가사 보존 |
| `test_p3_filename.py` | 4포맷 rename 후 복원/mtime, 충돌·링크·리비전·권한·busy, no-replace, sidecar 및 jobs 실패 후 전진 복구, 모호한 상태 차단 |
| `test_p5_command001.py` 관련 부분 | SYLT/USLT/LRC 저장·복원 시 LRC 유지, 기존 LRC 충돌, LRC 공개 후 저널 완료 실패, 음악 교체 후 LRC 실패 복구, LRC rename 및 옵션 보호 |
| `test_p7_id3.py` | v2.3/2.4 다중값, v2.2 변환/무태그 기본 버전, 미선택 프레임 손실 및 MP3 오디오 손상 주입 차단, ID 갱신 |
| `test_p10_command007.py` 관련 부분 | 편집 가사에 옛 시간정보 재사용 금지, 기존 SYLT/LRC 보존, 후보 바인딩 |
| `test_p6_job_store.py`, P4 일부 | 기록 replace 실패 시 마지막 정상 JSON 유지, 활동 상태/예외 정리. 음악 전체 트랜잭션의 복구 보증은 아님 |
| 배포 PowerShell/준비 JS 소스 | 구성 보존·허용 목록에 적힌 파일 존재 검사. 새 import 모듈이 목록에서 빠지는 역방향 누락까지 전부 검출하지 않음 |

### 우선 보강할 시나리오

1. **자동 rename의 경쟁·중단(높음):** LRC 없는 경로는 후보 이름 존재 검사 후 os.replace한다. 외부 프로세스가 그 사이 목적 음악/sidecar를 만들면 덮어쓰기 위험이 있다. sidecar만 이동한 순간 프로세스 종료, 음악 실패 뒤 sidecar rollback 실패, 기존 alias 재사용/충돌에 대한 전체 상태 행렬이 없다. 정상 충돌 테스트와 커널 no-replace 테스트는 다른 경로다.
2. **공개 경계별 중단/지속성(높음):** 중앙 백업 디렉터리 공개, sidecar 공개, stage fsync, 음악 replace, 저널 complete 각각의 직전/직후 종료·재시작을 조합한 검증이 부족하다. storage의 백업 공개/음악 replace는 디렉터리 fsync를 하지 않는 반면 rename/LRC는 한다. 원자적 이름 교체가 전원 장애 내구성 전체를 보장한다는 결론을 내릴 수 없다.
3. **음악 완료 후 실패의 응답/차단(중상):** LRC 영구 실패나 최종 describe 오류는 이미 바뀐 음악에도 파일별 failed를 만들 수 있다. P5는 전진 복구를 검증하지만 전체 HTTP 결과/기록/재시도 조합은 부족하다. save_job의 check_ready는 OPERATION_LOCK 취득 전이고 perform_save_job은 배치 각 파일 전에 다시 확인하지 않는다. 앞 요청/곡이 복구 차단을 만든 뒤 이미 대기한 요청 또는 다음 곡의 진행 여부를 추가 검증해야 한다.
4. **저널 손상·연결(중상):** LRC pending의 before/after/모호함, 잘못된 JSON/root/path/필드, 외부 LRC 생성, 음악 rename과 pending LRC 조합, complete 기록 후 sync 실패를 조합해야 한다. LRC recover의 JSON/키 예외는 StorageError로 모두 정규화되지 않고 시작 핸들러는 StorageError만 잡는다. 현재 동작을 먼저 기록한 뒤 차단/가용성 정책을 별도로 설계한다.
5. **포맷 경계(중상):** MP3 손상 주입 외에 FLAC/OGG/M4A 오디오 손상, 큰 Vorbis 헤더/페이지 경계·체인/다중 스트림, 잘린 metadata, 복수 mdat 등 지원 한계의 실패 닫힘 검증이 부족하다. 오디오 구간 비교는 재생 가능성 전체 검증이 아니다. FLAC STREAMINFO나 MP4 재생 메타데이터, OGG 헤더의 의미 보존도 따로 검토해야 한다.
6. **미선택 비표준 태그(중간):** MP3 프레임 비교와 동등한 전체 임의 메타데이터 비교는 나머지 포맷에 없다. 다중 커버/다국어 가사/미선택 다중값/알 수 없는 atom 또는 comment를 생성 fixture로 확인한다. 현재 읽기가 대표값만 보여 주는 경우 단순 FileInfo 비교만으로는 손실을 탐지하지 못한다.
7. **외부 변경·자원·파일 속성(중간):** 백업 도중/마지막 리비전 이후 외부 교체, symlink/상위 디렉터리 변경, 복원 중 백업 손상, chmod/fsync/link/replace 각 실패, ENOSPC, 큰 파일 메모리 사용을 보강한다. 현재 RLock은 프로세스 내부 보호이며 파일 잠금/다중 worker/SMB 쓰기 잠금이 아니다. 복사는 mode만 명시적으로 보존하므로 owner/ACL/xattr/hardlink 의미를 보장한다고 주장하지 않는다.

이 항목들은 정적 근거의 위험 또는 미검증 범위다. 운영 데이터 손상이 발생했다고 단정하지 않는다. mocked 예외 테스트와 실제 프로세스 종료 테스트, 전원 장애 검증도 서로 구분한다.

## 5. 단계별 실행 계획

각 번호/하위 번호는 별도 수정·검증·로컬 커밋 단위다. 다음 작업에서 별도 지시가 있을 때만 실행한다. **모든 단계 공통:** 기존 API/JSON 및 백업·저널 schema, 최초 원본/해시·경로 alias, 후보/리비전/옵션, 기존 잠금 범위를 유지한다. 새 모듈마다 `deploy-nas.ps1` 허용 목록, Dockerfile의 `COPY app/` 및 `.dockerignore !app/**`, 준비 검사와 복구 문서의 동반 복원 파일을 함께 확인/갱신한다. 의존성 추가는 기본적으로 없다.

### 0. 실패 계약 고정 — 매우 낮음, 가장 먼저

- 대상: P0/P3/P5/P6/P7 및 저장 HTTP 회귀 테스트. 새 production 모듈 없음.
- 0a: storage stage/백업/음악 replace 경계의 주입 테스트. 0b: LRC/rename/작업 기록의 교체 후 실패 테스트. 각각 독립 커밋.
- 보존: 현재 성공/부분 성공/실패와 파일 실제 상태를 구분한다. 알려진 위험 동작을 바람직한 계약으로 고정하지 않고 발견된 결함은 별도 이슈로 기록한다.
- 회귀: 생성 4포맷, 최초 원본/sidecar 불변, 각 실패 뒤 현재 경로·바이트·저널·복원 가능성 assertion. 파서/쓰기 실패가 실제 주입됐는지도 확인.
- 복구: 테스트 변경만 되돌리면 된다. 운영 데이터 영향 없음.
- NAS: 배포 불필요. 격리 Linux 테스트만 대상.

### 1. 파일 입출력·공통 계약 분리 — 낮음

- 1a 대상: storage._json_bytes/_new_file/_replace_file → `app/file_io.py`의 encode_json/create_file/replace_file. 초기에는 storage 호환 wrapper와 호출 경로를 유지한다.
- 1b 대상: StorageError → `app/storage_contracts.py`; rename_service.sync_dir/no_replace → file_io. 필요 공통 digest/revision 및 경로·쓰기 검사는 `app/music_files.py`로 이동한다. OPERATION_LOCK은 기존 객체 유지 또는 공통 모듈의 같은 객체 재노출.
- 1c 대상: rename_service/lyric_assets/job_store/preferences의 위 private 호출을 명시 API로 전환. 한 소비자군씩 독립 커밋한다. 하위 모듈이 storage를 다시 import하지 않도록 한다.
- 보존: hard link create-only, 같은 폴더 stage, mode, 예외, fsync 호출 위치/순서, Linux renameat2 미지원 실패. 이 단계에서 fsync 추가나 retry 변경을 섞지 않는다.
- 회귀: P0/P3/P5/P6, preferences 관련 P2; patch 지점을 이동해 실패 주입이 계속 효력을 갖는지 확인. import 경로/StorageError와 RLock 객체 동일성, 새 모듈 배포 누락 검사.
- 복구: 해당 커밋과 동반 import 파일을 한 묶음으로 되돌린다. 데이터 형식 변환 없음.
- NAS: 각 완결된 소비자 전환 단위가 회귀·빌드 검증을 통과하면 조건부 가능. 초기 wrapper만 추가하는 중간 상태는 배포 실익 없음.

### 2. 최초 백업 저장소 분리 — 낮음~중간

- 대상: storage.ensure_backup/_verify_backup 및 alias 계산 → `app/backup_store.py`의 ensure_first_backup/verify_backup/path_alias. storage는 호환 wrapper를 남기고 rename_service가 공개 API를 사용하도록 한다.
- 크기: 2a 검증 함수 이동, 2b 신규 백업 생성 이동, 2c alias 계산 공통화는 각각 별도 커밋. alias 존재 시 동작 차이를 여기서 바꾸지 않는다.
- 보존: 모든 파일명/버전/직렬화 bytes/경로 해시/최초 원본, legacy 차단, sidecar 누락 복구 조건, 검증 횟수/시점. Tags backup version 1과 NAS manifest version 2를 혼동하지 않는다.
- 회귀: P0 백업 손상 전체, 중앙 공개 뒤 sidecar 실패의 재개 및 현재 내용 불일치 차단, P3 alias 후 복원, 기존 형식 fixture 호환, 백업의 중첩 경로/비ASCII 경로.
- 복구: 코드만 전 단계로 복귀. 백업을 재생성·삭제하거나 schema를 갱신하지 않는다.
- NAS: 각 완결 단위 조건부 가능. 기존 백업 fixture로 양방향 코드 호환 확인 필요.

### 3. 오디오 검증 경계 분리 — 중간

- 대상: tags._layout/_audio_bytes/_skip_id3v2/_syncsafe/_top_atoms/_ogg_header_end → `app/upstream/audio_layout.py`; 공개 extract/compare 인터페이스를 두고 tags의 기존 이름을 호환 재노출한다. storage.save/restore의 private 참조만 전환한다.
- 보존: 파싱 알고리즘, 예외, MP3/FLAC/M4A/OGG 지원 제한과 OGG sequence 정규화. 스트리밍 최적화·파서 재작성·지원 확장을 섞지 않는다.
- 회귀: P0 4포맷 저장/정확 복원, P7 손상 주입, 새 포맷 경계 fixture와 원본/변경 stage의 동일 추출 결과. 파싱 실패 시 음악 공개 금지.
- 복구: 호출과 파서 이동을 함께 되돌린다. backup layout 키는 그대로여야 한다.
- NAS: 생성 음원 및 지원 한계 테스트와 빌드 통과 후 조건부 가능.

### 4. storage.save의 정책·검증 분리 — 중간

- 4a 대상: 최종 텍스트/IDs/가사/SYLT 변경 판단 → `app/save_policy.py`의 입력 스냅샷 기반 계획 함수. 파일/네트워크 쓰기 없이 선택 결과를 반환한다. LRC 존재 검사는 I/O 단계에 남긴다.
- 4b 대상: stage 재읽기·ID3 보존·태그/커버/가사/오디오 비교 → `app/save_validation.py`. 예외와 검증 순서를 보존한다.
- storage.save에는 백업 → stage → 검증 → 최종 리비전 → LRC begin → replace → finish → rename 흐름이 명시적으로 남아야 한다. 아직 트랜잭션을 generic context manager로 감추지 않는다.
- 보존: 무변경 시 무백업/무쓰기/mtime, only_empty, marker/명시 가사 대체, ID 병합 우선순위, 커버 중복 prepare의 현재 출력, 이전 오류 의미와 반환값.
- 회귀: P0/P1 관련/P2 저장 매트릭스/P5/P7/P10 편집 가사, 저장 계획과 실제 결과 일치 및 손실 주입. 네트워크 호출 수·잠금 범위도 기존과 동일.
- 복구: 4a와 4b 각각 독립 되돌림 가능. 음악 완료 후 오류면 코드 rollback과 음악 복원은 별개다. 음악은 검증된 최초 백업을 사용한 명시 복원만 수행한다.
- NAS: 각 단계 회귀·동반 모듈 패키징 통과 후 조건부 가능.

### 5. main.save_one 요청 조정 분리 — 중간

- 5a 대상: 후보/체크 값·ID 대응 및 가사 선택 입력 검증 → `app/save_request_service.py`의 명시 입력 함수. 5b 대상: 자산 취득 및 storage 호출/결과 가공 이동. main에 HTTP 어댑터·기존 save_one wrapper를 남긴다.
- jobs, 토큰 조회, 설정, 네트워크 취득 함수를 인자로 전달한다. 새 모듈에서 main을 import하지 않는다. 별도 거대 전역 서비스 컨테이너는 만들지 않는다.
- 보존: 자동 후보값 신뢰 경계, 점수/범위, 가사 token, 구 API의 model_fields_set 분기, busy 처리, state_error·partial 집계, 프로세스 내 잠금 및 활동 예약. 저장 중 네트워크를 잠금 밖으로 옮기지 않는다.
- 회귀: P0 HTTP 위조/리비전/동시성, P2 후보/옵션/가사/진행률, P3 busy 예약, P10 편집 및 바인딩, 요청별 네트워크 mock 호출 확인.
- 복구: HTTP wrapper와 새 모듈을 동반 rollback. 작업 기록 schema 그대로, 기존 기록 삭제 없음.
- NAS: 5a/5b 각각 저장 HTTP 회귀와 import/배포 검사 통과 시 조건부 가능.

### 6. tags.py 포맷 구현 분리 — 중간~높음

- 6a: Tags/Ids/FileInfo·예외·상수 → `upstream/tag_models.py`, tags에서 같은 객체 재노출. 필드/기본값/직렬화 유지.
- 6b: Vorbis 공통 함수 및 FLAC/OGG read/write → `upstream/vorbis_tags.py` (FLAC/OGG 코덱 동작은 별도 함수 유지).
- 6c: MP4 read/write/IDs/track 처리 → `upstream/mp4_tags.py`.
- 6d: ID3 read/write/IDs/preserved_frames → `upstream/id3_tags.py`. 버전 변환·다중값 때문에 마지막.
- 각 하위 단계는 별도 커밋. tags는 read_file/write_file/backup 공개 진입점과 포맷 dispatch를 유지한다. 코덱에서 tags facade 역참조 금지; 공유 모델/필요 helper만 leaf로 둔다. 옛 backup/restore 제거는 포함하지 않는다.
- 보존: 프레임/atom key, None/빈값 의미, 그림 교체 정책, ID3 버전·정렬/다중값·unknown_frames, upstream 예외/라이선스 고지.
- 회귀: 해당 포맷의 기존 P0/P2와 임의 메타데이터 보존 fixture, ID3는 P7 전체; 각 단계마다 다른 포맷 dispatch의 최소 저장/복원 smoke 확인. 기존 backup layout/옛 wrapper의 import 호환.
- 복구: 실패한 코덱 단계만 facade와 함께 되돌림. backup schema 변경 없음.
- NAS: 코덱별 검증 완료 시 조건부 가능. 다포맷 일괄 이전은 피한다.

### 7. 동작을 강화하는 별도 후속 과제 — 높음, 초기 분리와 혼합 금지

- 7a 대상: storage.save의 LRC 없는 자동 rename, tags.rename_file 호출 경계. 자동 이름 생성 규칙을 유지하면서 `rename_service`의 no-replace/지속 저널 경로로 통합한다. 모든 호출에 작업 문맥을 어떻게 전달할지와 기존 직접 storage.save 사용자의 호환을 먼저 결정한다.
- 회귀: 외부 목적 파일 생성 경쟁, 모든 이동 경계 중단, alias 재사용, sidecar rollback 실패, 정상 번호 붙이기/현재 partial 결과, 기존 pending 저널 재생. 구/신 코드 모두 이해 가능한 저널 사용.
- 복구: pending 정리·전진 복구 가능성을 확인한 뒤만 이전 코드로 복귀. 이름을 임의로 반대로 이동하거나 저널을 삭제하지 않는다.
- 7b 대상: backup_store/file_io/storage 음악 공개의 디렉터리 fsync 및 오류 전달. 새 모듈 없이 내구성 순서 강화만 별도 커밋한다.
- 회귀: 파일/디렉터리 fsync·link·replace 실패와 생성 파일만 사용하는 종료/재시작 검증. 공개된 뒤 발생한 오류를 “미변경”으로 오보고하지 않도록 한다.
- 복구: 내구성 오류 때 기록/실제 파일을 보존하고 검증; 자동 최초 백업 재작성 금지. 코드 rollback은 기존 데이터 형식 지원 확인 후 수행.
- 7c 대상: main.perform_save_job 및 lyric_assets.recover의 복구 차단 재확인/오류 계약. 이미 대기한 요청·배치 후속 곡, JSON 손상, 음악 완료 후 실패 응답을 따로 다룬다. 작업/응답 schema 호환을 먼저 정한다.
- 회귀: 요청 A가 차단을 만든 뒤 요청 B, 배치 두 번째 곡, startup 손상 저널, 실패 후 재스캔/재시도/원본 복원. 보호 목적은 유지하며 무조건 재시도하거나 차단을 지우지 않는다.
- 복구: 기존 schema·저널 보존, 필요 시 기존 코드로 rollback하되 미완료 복구 상태를 우회하지 않는다.
- NAS: 7a/7b/7c 모두 설계·실패 행렬·격리 Linux 복구 검증 완료 전 보류. 기존 위험을 실제 재현하면 순수 구조 분리보다 먼저 별도 안전성 수정 작업으로 승격할 수 있다.

## 6. 배포·복구 및 다음 작업의 완료 기준

- “NAS 조건부 가능”은 이번 배포 허용이나 검증 완료를 의미하지 않는다. 다음 지시에 따라 생성 음원만 쓰는 Linux 컨테이너에서 관련 회귀·빌드/패키징을 통과한 뒤 결정한다. 실제 음악/data는 테스트에 마운트하지 않는다.
- 새 모듈은 명시 전송 목록에 반드시 포함한다. Docker context가 app 전체를 포함해도 SCP 목록이 빠지면 소스가 NAS에 도착하지 않는다. 배포 검사에는 active import 모듈의 목록 누락 방향도 추가한다.
- 기존 배포 스크립트의 서비스 단독 재생성·설정/마운트 보존을 유지한다. worker=1 전제, 기존 이름/경로 및 승인된 music rw를 바꾸지 않는다. 자동 rollback은 없다는 배포 문서의 계약을 유지한다.
- rollback은 검증된 이전 코드/이미지로 수행하고 동반 모듈을 맞춘다. 현재 소스 변경을 강제 reset하거나 운영 data를 구버전으로 통째로 덮지 않는다. 백업/sidecar/renames/lyric-assets/jobs를 함께 보존하고, 구버전의 기록 해석 가능성을 먼저 확인한다.
- 복구 문서에는 오래된 jobs.json 표현과 새 jobs/<id>.json 설명이 공존한다. SYLT 설명 중 v2.3 고정 표현도 현재 v2.3 유지/기본 v2.4 코드와 다르다. 후속 구현 때 관련 절만 정정하되 이번에는 이 문서 외 수정하지 않았다.

**다음 작업의 첫 대상은 0a: `tests/test_p0_storage.py`의 음악 공개 경계 실패 계약 보강이다.** 첫 production 수정은 1a의 file_io 분리다. 실제 Git 작업본 대조 후 한 단위만 구현·관련 회귀·diff 검토·명시적으로 허용된 로컬 커밋 순서로 진행한다. 이번 #013은 여기서 종료하며 코드 수정 지시를 기다린다.

### 완료/미완료 구분

- 완료: 요청된 호출 흐름, 백업/검증/교체/복구 순서, rename/LRC 관계, private 의존성, 포맷 차이, 책임 혼재, 테스트 보호/공백, 단계별 대상·불변조건·회귀·복구·NAS·위험도 계획.
- 의도적으로 미수행: 동적 재현, 회귀 실행, 음악/운영 데이터 검사, NAS 상태 확인, Git 기준 및 배포본 동일성 확인. 이 항목들은 정적 분석의 결론으로 대체하지 않는다.
- 진행 기록: 초기 호출 흐름 분석 후 1차 저장, 포맷/의존성/테스트 검토 후 2차 갱신, 단계별 계획 작성 후 이 완료본으로 갱신했다.

## #014 진행 기록 — 실제 Git 작업본

상태: 환경/소스 대조 완료, 테스트 작성 전. 작업 위치 `C:\Codex\music-tag-filler-nas`, 시작 HEAD `d43b98c`.
기존 변경 `AGENTS.md`, 미추적 `.aider.chat.history.md`, `.aider.input.history`는 보존하고 커밋 대상에서 제외한다.
#013 문서가 실제 작업본에 없어 분석 문서를 복사했다. 위 #013의 Git 미확인 설명은 당시 분석 폴더에 관한 역사적 기록이다.
저장/태그/rename/LRC 4개 소스는 분석본과 SHA256 동일. main은 #011/#012 scan/lyrics 서비스 분리, P0 setUp은 lyrics 캐시 정리 위치 변경이 있다. AST 비교상 save_job/perform_save_job/revert_file/시작 복구는 동일; save_one은 구 API 가사 조회가 _lyrics_service.legacy_lookup으로 위임된다. storage.save 호출과 교체 경계는 동일하다.
Python 3.14.6, PIL/uvicorn/mutagen/FastAPI 및 로컬 FFmpeg 사용 가능. Docker CLI/WSL 배포판은 확인되지 않았다. 운영 음악/data/NAS 접근 없음.

### #014 1차 실행/환경 분리 기록

신규 테스트 11개 작성. 초기 실행은 Windows os.fsync(read-only fd)의 EBADF 때문에 백업 단계에서 차단됐다. 이는 Linux용 기존 코드의 Windows 실행 제약이며 저장 결함으로 분류하지 않는다. 기본 Python의 musicbrainzngs 누락도 확인해 TEMP 전용 의존성 경로를 마련했다. requirements/운영 의존성 파일은 수정하지 않았다.
Windows 보조 실행에서 읽기 전용 fsync EBADF만 임시 처리했을 때 신규 직접 테스트 10개는 통과했다. HTTP 사례는 job_store의 Linux 전용 O_DIRECTORY 때문에 아직 의도한 보고 결함 assertion까지 도달하지 못했다. 이 상태를 결함 재현 성공으로 보고하지 않는다. expectedFailure가 준비/주입 실패를 숨기지 않도록 cleanup에서 최종 assertion 도달 여부를 추가 검사했다. 다음 실행에서는 디렉터리 sync도 보조 실행기 범위에서 분리하고 정확한 실패 지점을 확인한다. Linux fsync/renameat2/전원 장애 검증은 미수행이다.

### #014 최종 검증 기록

상태: **0a 테스트 작성·Windows 보조 검증 완료. Linux 정규 검증은 환경 부재로 미완료.** 운영 코드 수정 없음. NAS 접속/배포 및 push 없음.

추가한 `P0Tests.test_boundary_*` 11개(메서드 수; subTest를 별도 테스트 수로 합산하지 않음):

| 테스트 접미사 | 실패 지점과 확인 사항 |
| --- | --- |
| first_backup_partial_copy_failure | 4포맷 최초 original 복사의 일부 바이트 기록 후 실패; 중앙 최종/sidecar 미공개, 임시 디렉터리 정리, 재시도/정확 복원 |
| first_backup_metadata_failure | 임시 upstream 태그 백업을 실제 기록한 뒤 예외; 임시 원본/태그 파일 정리, 음악 불변, 재시도 |
| central_published_sidecar_link_failure | 중앙 백업 공개 후 sidecar hard link 직전 실패; 임시 sidecar 정리, allow_missing 백업 검증, 최초 중앙 파일들의 바이트 불변 및 재개 |
| stage_creation_failure | 음악 stage mkstemp만 선택적으로 실패; 최초 백업/sidecar 정상, 잔여 파일 없음, 재시도 |
| stage_partial_copy_failure | stage에 일부 바이트 복사 후 실패; stage 정리, 음악/최초 백업 보존, 재시도 |
| stage_write_then_failure | 실제 tag writer가 stage에 새 제목을 쓴 것을 확인한 뒤 실패; 원본 음악 보존 및 stage 정리 |
| stage_validation_failure | 실제 stage readback 후 반환 태그만 변조해 검증 불일치; 실제 음악 공개 전 차단, 백업 보존 |
| stage_fsync_failure_before_music_replace | 유효 백업 선생성 후 stage fsync 예외; 호출 1회·replace 미호출, 음악/백업 보존 |
| music_replace_failure_keeps_previous_edit | 4포맷의 기존 편집본에서 음악 대상 replace 직전 실패; 현재 편집본 유지, 최초 원본/sidecar 불변, 재시도/최초 바이트 복원 |
| post_replace_describe_failure_preserves_recovery | 4포맷 음악 교체 후 최종 describe 실패; 실제 새 음악 확인, 옛 리비전 재시도 차단, 최신 동일값 skipped, 최초 원본 정확 복원 |
| http_post_replace_failure_reports_committed_change | HTTP 저장의 음악 완료 후 describe 실패; 변경된 음악/정상 백업/복원 가능성을 확인하고, 원하는 partial 보고와 현 failed 보고의 불일치를 expectedFailure로 추적 |

공통 helper는 현재 경로·음악 존재, 중앙 원본 크기/전체 SHA256 및 검증 함수, 중앙 모든 파일의 바이트 snapshot, 최초 sidecar 보존, `.backup-*`/`.tagtxn-*`/`.tagbak-*` 정리를 확인한다. 실제 함수 호출 횟수·선택 대상·stage 내용 또는 주입 예외 객체/원인을 확인하므로 mock이 다른 경로에 걸린 것을 성공으로 처리하지 않는다. HTTP expectedFailure는 cleanup에서 최종 결함 assertion 도달 여부까지 검사하므로 준비/주입 실패가 예상 실패로 숨겨지면 별도 실패한다.

#### 실행 결과와 환경 한계

- 최종 대상: `test_p0_storage` 전체 36개 + `test_p7_id3` 8개 = **44개 실행, 41개 통과, 일반 실패 0, 오류 0, 예상 실패 1, 건너뜀 2**.
- 신규 11개만 보면 통과 10개 + 아래 보고 결함의 예상 실패 1개. 기존 관련 테스트는 통과 31개 + 건너뜀 2개다.
- **위 수치는 Windows 보조 단위 검증이다. Linux/NAS와 동일 환경의 정규 통과로 해석하면 안 된다.** 실행기의 두 격리 처리는 (1) 실제 os.fsync를 우선 호출하고 Windows EBADF이며 fstat상 유효한 descriptor일 때만 read-only 제약을 우회, (2) rename_service.sync_dir를 호출 기록 stub으로 대체한 것이다. 최종 실행에서 각각 292회/33회였다. fsync 자체 실패 주입 테스트는 내부 mock이 이를 다시 덮어써 예외·replace 차단을 실제 검증했다.
- 이 보조 처리는 TEMP 실행기 `music-tag-014-run.py`에만 있으며 테스트/운영 소스에 fsync 우회 코드를 추가하지 않았다. 파일 내용·해시·실제 copy/write/link/replace·재시도/복원은 실행했다. 실제 Linux fsync, 디렉터리 내구성, renameat2, 강제 프로세스 종료/전원 장애는 검증하지 않았다.
- 건너뜀: 기존 read-only 마운트 테스트의 원래 skip 1개; Windows에 os.statvfs가 없어 기존 revision/readonly 복합 테스트를 실행기에서 skip 1개. 후자는 보조 처리 전 기존 테스트 그대로 실행하여 AttributeError를 확인했다. 신규 post-replace 테스트에서는 옛 리비전 차단을 별도로 통과했다. 기존 보호 테스트 소스는 제거/완화하지 않았다.
- Python 3.14.6, FFmpeg 로컬 생성. TEMP 의존성의 FastAPI 0.110.0/Starlette 0.36.3/Uvicorn 0.29.0/Mutagen 1.47.0/requests 2.31.0은 지정 버전이다. Pydantic 2.14.1, Pillow 12.3.0을 사용했다. NAS Dockerfile의 Python 3.11/Pillow 10.3.0과 동일하지 않다. 의존성 파일/전역 설치는 변경하지 않았다.
- 초기 import 실패(musicbrainzngs 누락), Windows read-only fsync 오류, HTTP 기록의 O_DIRECTORY 오류를 순서대로 환경 문제로 분리했다. 최종 예상 실패 traceback은 정확히 `'failed' != 'partial'`인 마지막 assertion이며 앞선 실제 변경/복원/주입 검증을 모두 거쳤다.

Linux 환경이 준비되면 운영 음악/data 마운트 없이 문서화된 검증 컨테이너에서 아래 관련 회귀를 **호환 stub 없이** 실행해야 한다. 이 재검증 전 Linux 정규 검증 완료로 표시하지 않는다.

```sh
PYTHONPATH=.:tests python -B -m unittest test_p0_storage test_p7_id3 -v
```

Windows 보조 실행 재현: 프로젝트 루트에서 TEMP 의존성 경로를 PYTHONPATH로 지정하고 `python -B $env:TEMP\music-tag-014-run.py`를 실행했다. 이 임시 실행기는 위 두 sync 격리와 statvfs 테스트 skip만 적용하고 P0/P7을 로드하며, expectedFailure traceback이 지정한 마지막 상태 불일치인지 추가 assertion한다. 임시 실행기/의존성/실행 로그는 커밋하지 않는다.

#### 별도 문제 STORAGE-014-01: 교체 후 상태 읽기 실패의 보고

생성 음원 HTTP 저장에서 storage.save의 최종 describe에 OSError를 주입하면 음악은 새 제목으로 실제 교체되고 최초 백업/sidecar와 원본 복원은 정상인데 perform_save_job은 이를 일반 failed(배치 saved=0)로 보고한다. 호출자는 파일 변경 여부를 그 상태만으로 구분할 수 없고 작업의 기존 original/revision도 갱신되지 않는다. 이를 정상 성공/미변경 계약으로 고정하지 않았다. 예상 실패 테스트의 원하는 최소 계약은 해당 곡의 partial 보고이며, 구체적인 committed 플래그·최신 리비전·응답/작업 schema는 별도 설계가 필요하다. 이번 작업에서 운영 코드를 자동 수정하지 않았다.

0b(LRC/rename/기록의 교체 후 실패) 테스트 설계·작성은 진행 가능하다. 다만 실제 Linux 저널/renameat2 경로 실행은 Linux 환경 확보 후 검증해야 하며, 구조 분리 단계 진입 전에는 0a의 정규 Linux 재검증도 완료해야 한다.

커밋 대상은 `tests/test_p0_storage.py`, `docs/STORAGE_REFACTOR_PLAN.md` 두 파일뿐이다. 기존 AGENTS/Aider 변경은 보존한다. 전체 diff --check의 AGENTS.md 공백 경고는 기존 변경에서 발생했으며 이 작업의 검사 대상과 구분한다.
