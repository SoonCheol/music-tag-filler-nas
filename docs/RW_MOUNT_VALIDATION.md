# NAS 음악 쓰기 마운트 전환 검증

2026-10-21 사용자 요청으로 `/volume1/Multimedia/Music:/music:ro`를 `/music:rw`로 전환했다.
운영 음악을 저장·스캔·수정하는 API는 호출하지 않았다.

## 위험과 사전 확인

마운트 변경 자체는 음악 바이트를 변경하지 않지만 이후 저장·이름 변경·되돌리기가 실제 파일에 적용된다.
앱의 최초 백업·무결성 검사·실패 시 차단은 유지된다. 최초 백업과 임시 저장에는 추가 공간이 필요하다.
전환 전 음악 볼륨 여유 약 965 GiB, 데이터 볼륨 여유 약 801 GiB, data 크기 약 1.3 MiB였다.
완료되지 않은 운영 작업은 없었다. 독립 음악 백업이나 NAS 스냅샷의 존재는 검증하지 않았다.
앱 HTTP 인증이 없고 기존 의존성 보안 공지가 있으므로 쓰기 권한 확대는 접근 통제의 중요성을 높인다.
관련 제한은 [보안 점검](SECURITY_AUDIT_KO.md)을 따른다.

## 실제 NAS 격리 테스트

운영 이미지 `sha256:467fd3b7a2c2f254aff3f2b316ae4eda46e9dc725683a377e2408863d6f00ca0`를 그대로 사용했다.
운영 음악/data 대신 별도 NAS 디렉터리를 마운트하고 네트워크를 차단한 일회용 컨테이너에서 실행했다.
`tests/verify_nas_rw.py`는 일치하는 임의 토큰의 마커만 있는 빈 폴더 두 개를 확인한 후 앱을 가져온다.
초기 실행은 테스트 스크립트를 data 폴더에 함께 두어 안전 검사에서 차단됐다. data를 별도로 분리한 뒤 통과했다.

| 생성 음원 | 저장·HTTP 재조회 | 체크하지 않은 태그·기존 가사 보호 | 최초 백업 보존·검증 | 되돌린 전체 바이트 SHA256 일치 |
| --- | --- | --- | --- | --- |
| MP3 | 통과 | 통과 | 통과 | 통과 |
| FLAC | 통과 | 통과 | 통과 | 통과 |
| M4A | 통과 | 통과 | 통과 | 통과 |
| OGG | 통과 | 통과 | 통과 | 통과 |

결과 JSON: NAS 프로젝트의 `rw-validation-66759e4c882f7a9e0d6c8f8e3ef3f533/isolated-data/validation-report.json`.
생성 음악: 운영 Music 밖 `/volume1/Multimedia/MTF-generated-rw-test-66759e4c882f7a9e0d6c8f8e3ef3f533`.
운영 경로를 마운트하지 않는 P0/P1/P2 회귀 테스트도 운영 이미지에서 55개 모두 통과했다.

## 백업과 적용 결과

NAS 프로젝트의 `deploy-backups/rw-mount-20261021-66759e4c/`에 다음을 보존했다.

- 원래 Portainer 정의의 tar 원본과 YAML, 변경 전후 정규화된 Compose 정의
- 변경 전후 컨테이너 inspect, 다른 컨테이너 ID 목록
- `data-before.tar`와 SHA256, 최종 웹 응답

원래 Portainer YAML의 음악 볼륨 한 줄만 ro→rw로 바꿨다. 저장소 YAML로 원본을 덮어쓰지 않았다.
기존 이미지로 v6만 재생성했으며 이미지 빌드·sudo·권한 변경은 하지 않았다.
이미지·환경·명령·포트·리소스·재시작 정책·네트워크·data 마운트는 그대로임을 비교했다.
다른 컨테이너 ID도 동일하다. `tar -df data-before.tar`로 운영 data 내용 보존을 확인했다.
최종 상태 running, 재시작 횟수 0, `/music RW=true`, `/data RW=true`, 웹 HTTP 200, 진단 오류 없음이다.
재생성 직후 첫 연결은 초기화 중 끊겼으나 제한된 재시도에서 정상 응답했다.

## 이후 배포와 원복

자동 배포 JSON에 `MusicReadOnly: false`를 기록하고 실제 모드 불일치 시 배포를 차단한다.
이 항목이 없는 옛 설정은 안전하게 true로 처리한다. 예시 JSON과 현재 두 YAML도 승인된 rw에 맞췄다.
UI와 앱 저장 코드는 변경하지 않았다. commit·push는 하지 않았다.

Windows UI 2종, gitignore, 저장소 준비 검사(업로드 후보 70개), PowerShell 배포 안전성 테스트가 통과했다.
rw/ro 정의 불일치 거부, 일치하는 rw 보존, 이전 JSON의 ro 기본값, 잘못된 모드 자료형 거부를 확인했다.
`deploy-nas.ps1 -CheckOnly`와 `-PreflightOnly`도 통과했고 Windows에서 웹 HTTP 200을 확인했다.
초기 로컬 검사는 새 문서를 만들기 전 링크 누락과 샌드박스의 SSH 키 경로 접근 제한으로 실패했다.
문서 완성 및 승인된 검사 재실행 후 통과했다. `git diff`와 `git diff --check`를 확인했다.

ro 원복이 필요하면 별도 요청 후 원본 스택 tar를 Portainer의 기존 경로에 복원하고
`compose-original.yml`로 동일 서비스만 재생성한다. 이후 로컬 MusicReadOnly와 두 YAML도 true로 맞춘다.
마운트 원복만으로 이미 수행한 음악 편집이 취소되지는 않는다. 음악 복원은 검증된 원본 백업을 사용한다.
