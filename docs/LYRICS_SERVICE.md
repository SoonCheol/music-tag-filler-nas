# 가사 서비스 구조

`app/main.py`가 `LyricsService` 인스턴스 하나를 생성한다. 루트 경로와 후보 ID 계산 함수를 콜백으로 전달하며 서비스는 main을 import하지 않는다. API·작업 조회·경로/현재 리비전 검사·저장 트랜잭션은 main/storage에 남는다. 기존 main의 lookup_lyrics, remember_lyrics, selected_lyrics, rekey_lyrics는 호환용 위임 함수다.

서비스는 파일/리비전/쿼리별 캐시, 검증 토큰, 내용별 결과 캐시, 진행 중 Future와 RLock을 단독 소유한다. 사용되지 않던 _lyrics_pending은 제거했다. 성공 86400초·없음 1800초·오류 60초, 한도 2000 및 force/기존 토큰 보존 정책은 그대로다. 내용 키에는 제목·가수·길이·후보 에디션이 포함된다. 조회 네트워크는 저장 OPERATION_LOCK을 잡지 않으며 기존 Future로 중복 요청을 병합한다. 잠금 순서나 저장 보호 정책은 변경하지 않았다.

selected_lyrics는 루트·작업·경로·리비전·최종 제목/가수와 만료를 검증한다. 최종 저장의 후보 ID 검사는 main에 그대로 남는다. rekey_lyrics는 기존 파일명 변경 이벤트에서 토큰을 재발급한다. legacy_lookup은 구형 자동 저장 API의 BUSY 재시도·연속 실패 한도를 보존한다. clean_text, marker_only 등 태그 준비 유틸리티 호출과 실제 storage.save 연결은 main에 남는다.

현재 스캔 작업자는 가사 본문을 조회하지 않고 lyrics_status=skipped를 생성한다. 스캔 후 UI의 사전 조회/백그라운드 요청은 기존 엔드포인트를 거쳐 동일 서비스 인스턴스를 사용한다. scan_service와 UI는 변경하지 않는다.

캐시는 디스크에 쓰지 않는다. 서비스 재시작 후에는 가사를 다시 검색한다. 소스 복구 시 main.py와 lyrics_service.py를 같은 버전으로 복구하며 deploy-nas.ps1 허용 목록과 Docker COPY app/에 모두 포함한다. 운영 음악/data를 테스트에 마운트하지 않는다.

## #012 검증·배포 기록 — 2026-10-26 (KST)

main.py 1167 → 1052줄(-115), lyrics_service.py 신규 155줄. 핵심 4개 함수의 AST를 의존성 참조와 docstring 들여쓰기를 정규화해 비교했고 동일했다. 나머지 API 함수·scan_service·search_service·upstream/search_lyrics·storage·UI는 변경하지 않았다. 구형 저장의 네트워크 재시도 블록만 legacy_lookup 호출로 교체했다.

운영 음악/data 없는 /tmp/lyrics012-validation 컨테이너(--network none)의 생성 음원으로 관련 unittest 22개 최종 통과. 기존 가사/캐시/병합/토큰/후보/리비전/편집/시간 가사/네 포맷 저장/최초 백업 및 바이트 복원 검사와 신규 정책 검사 3개를 포함한다. 신규 TTL 테스트의 첫 실행은 이전 정상 토큰 보존 때문에 상태가 섞여 실패했으며, 사례마다 서비스를 격리한 후 실패 관련 클래스 3개만 재검사해 통과했다. 무관한 전체 회귀는 실행하지 않았다.

배포 PowerShell 보호 검사와 CheckOnly 통과. 기존 사용자 AGENTS.md의 공백 오류는 그대로 보존하고 변경 파일은 기본 diff --check로 별도 통과시켰다. 기존 배포 스크립트 실행 프로세스에만 core.whitespace=-blank-at-eol,-blank-at-eof를 지정했다. 저장소 설정은 변경하지 않았다.

기존 deploy-nas.ps1로 NAS 배포 완료. 소스 백업: /volume3/docker3/music-tag-filler-v6/deploy-backups/20261025-160724-6d0c0b01.
이미지: sha256:fec14793b0533bb4bbaf2ca4eb5fdf46c1051e377f369adcf0e6b96753f8d90f. 컨테이너 running, 재시작 0, 기존 이미지 태그/마운트/환경/포트 보존 및 HTTP/폴더 API 검사 통과. 배포 main/service 해시가 로컬과 같고 기존 OpenAPI와 완전히 동일했다.

실제 NAS 웹 UI에서 기존 작업을 읽어 현재 저장 가사 표시, 후보의 백그라운드 조회 완료(L 표시), 검색 가사 본문 표시를 확인했다. 최종 백그라운드 API는 operations=[]였다. 실제 운영 음악의 태그 저장·원본 복원·이름 변경·스캔이나 data 테스트 수정은 실행하지 않았다. GitHub push 없음.
