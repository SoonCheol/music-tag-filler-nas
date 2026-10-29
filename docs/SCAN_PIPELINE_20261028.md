# 스캔 파이프라인 개선 — 2026-10-28

사용자 요청에 따라 제안을 재검토했다. 후보를 중간에 공개하는 변경은 선택/저장 상태와의 경합을 다뤄야 하므로 제외했다. iTunes 결과만으로 MusicBrainz 검색을 생략하는 변경도 후보 범위를 바꾸므로 제외했다.

app/scan_service.py의 메타데이터 수집을 지연 생성기로 바꿨다. 기존에는 폴더의 모든 파일을 describe한 뒤 검색을 시작했다. 이제 한 파일을 읽으면 검색에 제출하고, 최대 3개의 검색이 진행 중이면 다음 파일 읽기를 기다린다. 추가 작업 스레드, 검색 출처/제한 변경, SHA256 검사 제거는 없다. 전체 파일 목록 수집 및 이어하기의 기존 리비전 검증은 여전히 먼저 수행한다.

효과는 첫 검색 시작 전 대기 단축과 읽기/네트워크 처리의 겹침이다. 전체 파일의 원본 태그가 미리 준비되던 동작은 달라져, 아직 차례가 오지 않은 행은 waiting 상태로 남는다. MusicBrainz 요청 대기 자체를 줄인 변경은 아니다. 실제 운영 총시간 개선율은 측정하지 않았다.

관련 임시 생성 음원 검사: test_p11_scan_service, test_scan_cancel, test_p8_scan_timing, P2Tests.test_resume_path_revision_insertion_removal_and_change — 16개, 2.754초, 모두 통과. 검색 3개가 막혀 있는 동안 네 번째 파일을 읽지 않는 assertion을 추가했다. 기존 테스트가 파일 바이트/mtime 보존, 취소, 이어하기, 동시성 제한, 기록 일치를 검증한다. 운영 음악/data는 테스트 컨테이너에 마운트하지 않았다. 전체 회귀/브라우저 자동화/GitHub push는 하지 않았다.

배포 전 진행 중인 스캔/저장 없음 확인 및 기존 deploy-nas.ps1 PreflightOnly 통과. 복귀 태그 music-tag-filler-nas:rollback-scan-pipeline-20261028은 이전 이미지 a22c37bf6b2f47f669401d343a0fa80c81345073a2603534653865c7b0986a55를 가리킨다.

배포 로그와 파일별 운영 데이터 해시 기록은 로컬 scratch/scan-pipeline/에 보관한다. NAS 임시 테스트 자료는 /tmp/codex-scan-pipeline에 남겼다.

기존 deploy-nas.ps1 배포 완료. 실행 이미지 sha256:ded449b8c86a3fd3889c543de150ddff418c3281d1dbaf281b887bcc289852a7, running/restarts=0. 실제 scan_service.py SHA256이 로컬과 일치했다. 스택 32 및 기존 마운트/설정 검증 통과. /, /api/folders, /api/jobs?summary=true HTTP 200. 배포 전후 /data 파일별 SHA256 전체 일치. 소스 백업은 /volume3/docker3/music-tag-filler-v6/deploy-backups/20261028-062610-fb4610f9. 실제 사용자 스캔 체감 및 총시간은 미검증이다.
