# 스캔 실행 서비스

`app/main.py`는 스캔 API의 요청 검증·작업 등록·취소·이어하기와 BackgroundTasks 등록을 담당한다. 기존 `scan_job(job_id, sub_path, opts, resume=False)`는 호출 시점의 공유 참조로 컨텍스트를 만들고 서비스만 호출한다.

`app/scan_service.py`의 책임:

- `ScanContext`: `jobs`, `_scan_clocks`, 음악/data 경로, `save_jobs`, 기존 `storage.OPERATION_LOCK`, 파일명 해석·후보 준비·파일 상태 콜백의 참조를 보관한다. 상태·경로·잠금을 새로 만들거나 복사하지 않는다.
- `scan_job`: 파일 수집·리비전 기반 이어하기, 메타데이터 읽기, 검색 작업 3개 병렬 실행, 진행 상태·결과 기록, 취소·실패 처리와 시계 정리. 내부 `lookup`도 함께 이동했다.
- `ScanCancellation`: 기존 작업 딕셔너리의 `cancel_requested`를 읽는다. 기존 Python 호출 호환성을 위해 `main.ScanCancellation`에서도 같은 클래스를 노출한다.
- `update_scan_timing`: 기존 경과 시간 누적·종료 시각 계산. 호출자는 기존 작업 잠금을 보유해야 한다.

`jobs`와 `_scan_clocks`의 소유자는 계속 main이다. `save_jobs`는 main에서 오류 상태를 검사하고 기존 RLock 안에서 시간 갱신과 `job_store.save`를 수행한다. 서비스의 상태 변경/저장 잠금 위치와 재진입은 기존과 같다. 네트워크 검색을 기다리는 동안 잠금을 유지하지 않는다.

서비스는 main을 import하지 않는다. 후보 순위·자동 선택·공개 API와 저장 코드가 함께 사용하는 `prepare_result`, `file_state`는 main에 유지하고 콜백으로 전달한다. `search_service`와 `job_service`는 기존 모듈을 그대로 사용한다. 시간 누적 딕셔너리와 실제 저장 콜백을 호출 시 전달하므로 테스트·런타임 경로 변경에도 이전 참조를 붙들지 않는다.

앨범 이미지·가사 조회, 저장·복원·이름 변경 트랜잭션, API 요청·응답, 작업별 JSON 형식을 바꾸지 않았다. 최초 스캔의 파일/총 수와 재개 시 유지·변경·누락 판단, 병렬 수, 취소 경계와 경과 시간 계산도 그대로다.

배포 허용 목록에 `app/scan_service.py`를 포함한다. 기존 Docker context의 `app/**`와 `COPY app/ ./app/`가 이미 새 모듈을 포함하므로 Docker 입력 규칙 변경은 필요 없다. 복구 시 main과 서비스를 같은 버전으로 복구한다.

관련 검증: `tests/test_p11_scan_service.py`, `test_p2_workflow.py`의 스캔/취소/이어하기/기록 검사, `test_scan_cancel.py`, `test_p8_scan_timing.py`의 DurationTests, `test_p6_job_store.py`. 생성 음원과 임시 data만 사용한다.
