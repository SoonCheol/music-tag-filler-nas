# v1.0.0 등록 진행 상태

## NAS 운영 이름 이전 완료 — 2026-10-21

Portainer 공식 stop·update·migrate API로 스택 ID 32를 `music-tag-filler`로 이전했다.
컨테이너·Compose 서비스·프로젝트는 모두 `music-tag-filler`, 이미지는 `music-tag-filler-nas:v1.0.0`이다.
기존 관리자 전용 접근 제어(ID 44), NAS 프로젝트/data 경로, `/music:rw`, `/data:rw`,
환경·포트 8000·기타 호스트 설정과 다른 컨테이너를 보존했다. 기본 네트워크 이름만 새 프로젝트에
맞춰 `music-tag-filler_default`가 됐다. 이전/새 인스턴스를 동시에 실행하지 않았다.

NAS 프로젝트의 `deploy-backups/name-migration-20261021/`에 원본 정의·컨테이너 설정과 data를 백업했다.
전후 data tar 비교가 일치했고 최종 컨테이너 running·재시작 0, Portainer active, 웹 HTTP 200이다.
기존 음악 파일은 수정하지 않았다. 이미 통과한 전체 테스트와 음원 저장 시험은 반복하지 않았다.

공식 migrate 호출 직후 컨테이너는 실행됐으나 Portainer의 inactive 표시가 남았다.
start 요청은 실패했으며, 동일 정의를 공식 update API로 적용해 active 상태로 정상화했다.
직접 DB 수정·원본 스택 삭제·토큰 출력은 하지 않았다.

아래 인증 대기와 현재/목표 비교는 이전 전의 역사적 기록이다. 현재 운영은
[현재 NAS](CURRENT_NAS.md)를 따른다. GitHub v1.0.0 태그·Release는 수정하지 않는다.

2026-10-21 사용자가 운영 이름 이전·commit·비공개 GitHub push·태그·Release 등록을 요청했다.
이 문서는 완료되지 않은 작업을 완료로 오인하지 않기 위한 재개 지점이다.

## 목표와 현재 운영

| 항목 | 현재 확인 | 최종 목표 |
| --- | --- | --- |
| Portainer 스택 | music-tag-filler-v6 | music-tag-filler |
| 컨테이너·Compose 서비스 | music-tag-filler-v6 | music-tag-filler |
| 운영 이미지 태그 | music-tag-filler-nas:v6 | music-tag-filler-nas:v1.0.0 |
| NAS 프로젝트·data | /volume3/docker3/music-tag-filler-v6 및 그 아래 data | 경로 변경 없음 |
| 음악·data | /music:rw, /data:rw | 변경 없음 |
| 포트·환경 | 8000:8000, MUSIC_ROOT=/music, DATA_ROOT=/data, TZ=Asia/Seoul | 변경 없음 |

새 고정 이름으로 이전한 뒤 업데이트는 이미지 버전만 변경한다. 기존 NAS 폴더 이름은 그대로 보존한다.
실제 이전 완료 전에는 현재 배포 JSON·현재 YAML을 새 이름으로 바꾸지 않는다.

## 완료한 준비와 검증

- 기존 배포 스크립트 `-BuildOnly`로 변경 빌드 입력을 백업·전송하고 빌드했다.
- 새 이미지 `music-tag-filler-nas:v1.0.0`을 만들었으며 기존 v6 태그를 원래 이미지로 복원했다.
- 새 이미지 ID: `sha256:148df465bfc0ecbfa3020834d479772e02d08ad8f6ce8877e0a45f79f1ded93b`.
- 원래 운영 이미지: `sha256:467fd3b7a2c2f254aff3f2b316ae4eda46e9dc725683a377e2408863d6f00ca0`.
- 롤백 태그: `music-tag-filler-nas:rollback-v6-20261021`.
- NAS 프로젝트의 `deploy-backups/release-v1.0.0-20261021/`에 원래 inspect, Portainer 정의 tar,
  data tar, 소스 tar를 보존하고 각 SHA256을 확인했다. 백업은 Git 대상에서 제외된다.
- 새 이미지에서 P0/P1/P2 테스트 55개 통과. 운영 볼륨을 테스트에 마운트하지 않았다.
- NAS의 격리된 생성 MP3/FLAC/M4A/OGG 모두 HTTP 저장·재조회·최초 백업 보존·정확한 바이트 복원 통과.
- 시험 결과는 NAS 프로젝트의
  `release-validation-83558190b66947f5878dd82e807aba96/data/validation-report.json`에 있다.
- 최초 두 테스트 명령은 토큰 환경변수/경로 전달 오류로 음원 생성 전에 중단됐다. 명령 수정 후 통과했다.
- 기존 Git 이력 14개 blob에서 개인키·일반 GitHub/AWS 자격 증명 패턴이 검출되지 않았다.
  현재 파일 내용 검사와 제외 규칙 검사는 별도로 유지한다. 기록은 재작성하지 않는다.
- 의존성은 기존 잠금 버전을 유지했다. 기존 4개 패키지의 보안 공지는
  [보안 보고서](SECURITY_AUDIT_KO.md)에 그대로 명시한다. 보안 취약점 해결판으로 발표하지 않는다.

## 인증 대기와 안전한 재개 순서

Portainer `/api/stacks`는 HTTP 401이다. 현재 연결된 브라우저가 없으며 인증 없이 DB를 편집하거나
인증을 재설정하지 않는다. GitHub는 공식 CLI의 브라우저 device 로그인을 시작했다.
기기 코드는 임시값이므로 이 문서에 저장하지 않는다. 로그인 실패/만료 시 새 절차를 시작한다.

1. Portainer 로그인 세션을 연결하고 원래 스택 ID·환경 ID·접근 제어·원본 정의를 확인한다.
2. 백업·이미지·활성 작업 없음·새 이름/8000 포트 충돌 여부를 다시 확인한다.
3. Portainer의 공식 스택 이름 이전 기능/API를 사용한다. 컨테이너명/서비스명 변경도 포함하고,
   중복된 두 인스턴스가 같은 data를 쓰지 않도록 기존 인스턴스를 먼저 정지한다.
4. 실패하면 새 인스턴스를 정지하고 백업 정의·원래 이미지로 원래 서비스를 복구한다.
   정상 data를 백업으로 덮어쓰지 않는다. 실제 data 손상이 확인된 경우에만 별도 복구 절차를 따른다.
5. 실제 스택 이름과 Compose 라벨, 단일 컨테이너, 이미지 ID, 마운트·환경·포트 및 웹/API를 확인한다.
   다른 서비스의 컨테이너 ID와 data 내용도 비교한다. 운영 음악 저장 테스트는 하지 않는다.
6. 실제 Portainer 정의 경로를 로컬 JSON에 기록하고 두 YAML·AGENTS·설치/복구/현재 NAS 문서를 갱신한다.
   배포 스크립트는 버전 변경 시 기존 정의의 이미지 태그만 갱신하고 롤백을 보장하도록 검증한다.
7. GitHub 인증 계정·대상 Private·쓰기 권한·기존 원격 브랜치/태그/Release를 확인한다.
   기존 원격 기록은 fetch해서 비교하고 강제 push·태그 재지정을 하지 않는다.
8. 검사한 파일만 commit하고 정상 배포를 확인한 최종 커밋을 push한다.
   해당 커밋에 v1.0.0 태그/Release를 만들고 실제 결과·커밋 SHA·이미지 ID를 기록한다.

## GitHub 등록 완료 — 2026-10-21

SoonCheol 인증과 repo/workflow 권한을 확인했고 대상 저장소가 Private임을 확인했다.
기존 원격은 비어 있었다. 기존 원본 이력을 보존한 master 브랜치를 push하고 추적 설정을 연결했다.

- 릴리스 커밋: `2819fd96ef69adc83ca3fbf5ce0ba2520d3653fc`.
- 태그: `v1.0.0` (annotated tag, 기존 태그 덮어쓰기 없음).
- [정식 Release](https://github.com/SoonCheol/music-tag-filler-nas/releases/tag/v1.0.0): 발행 완료, Draft/Prerelease 아님.
- 최초 브랜치 push의 GitHub Actions 검증 성공. 태그 push 실행은 발행 직후 진행 중이었다.
- Windows keyring의 GitHub CLI 인증과 Git credential helper, origin/master 추적 연결을 설정했다.
  토큰을 파일·문서·URL에 기록하지 않았다. 토큰 자체를 출력하거나 commit하지 않는다.

위 GitHub 등록 작업은 반복하지 않는다. 새 이름으로의 NAS 운영 이전은 여전히 Portainer 인증 대기다.
향후 이전 결과는 별도 커밋/후속 버전으로 기록하며 발행한 v1.0.0 태그를 재지정하지 않는다.
상단의 인증 대기 설명과 재개 순서 중 GitHub 미등록 부분은 이 완료 기록으로 대체한다.

공식 절차: [Portainer 스택 이름 이전](https://docs.portainer.io/user/docker/stacks/migrate),
[GitHub 인증](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github).
