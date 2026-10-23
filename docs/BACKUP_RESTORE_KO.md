# 프로그램·설정·음악 백업 및 복구

## 무엇을 어디에 보관하는가

| 대상 | GitHub 보관 | 별도 백업 |
| --- | --- | --- |
| 소스·테스트·빌드/Stack·문서·라이선스 | 비공개 저장소에 commit 후 push | Git bundle 또는 추가 사본 |
| NAS 주소·계정·폴더·마운트 설명 | 사용자 승인에 따라 CURRENT_NAS.md에 기록 | 운영 기록 사본 |
| `/data/jobs.json` | 금지 | 작업·후보·경로·검색 상태 |
| `/data/settings.json` (존재 시) | 금지 | 체크 상태·국가·원문/로마자·표지 크기 등, 키를 포함할 수도 있음 |
| `/data/acoustid_key.txt` (존재 시) | 금지 | 암호화 백업 또는 암호 관리자 |
| `/data/backups/` | 금지 | 최초 음악 전체 바이트·태그·무결성 manifest·별칭 |
| 음악 원본과 옆의 `*.tagbak.json` | 금지 | NAS 스냅샷/독립 저장소에 함께 보관 |
| `deploy-nas.local.json`, SSH 개인키 | 금지 | PC의 암호화 백업/암호 관리자, 키는 분리 보관 |
| Docker 이미지 tar·inspect·실제 Stack 사본 | 금지 | 별도 사설 백업, checksum과 함께 |

**GitHub만으로 음악·data·비밀키를 복구할 수 없다.** 원본 Git 기록과 현재 문서에는
운영 메타데이터가 있으므로 저장소도 계속 비공개여야 한다.
보류 커버는 프로세스 메모리에만 있어 재시작 후 다시 선택해야 한다.

## 권장 주기

- 승인된 코드 변경마다 테스트→commit→요청받은 push. 아직 commit하지 않은 파일은 GitHub 백업이 아니다.
- 배포/설정 변경 전 data와 현 이미지 백업. 평소에는 NAS 백업 도구로 주기적 data/음악 스냅샷.
- 같은 NAS의 `deploy-backups/`는 소스 복구용이며 NAS 고장 대비 독립 백업이 아니다.
- 보관 기간/오프사이트 위치는 사용자가 정한다. 새 백업을 검증하기 전 기존 백업을 삭제하지 않는다.

## 일관된 수동 data·이미지 백업 절차

아래는 **나중에 실제 백업을 요청받았을 때 NAS SSH 셸에서 실행할 예시**다.
백업 경로 `/volume3/backups/music-tag-filler-v6`는 권장 예시이며 현재 존재 여부는 조사하지 않았다.
백업 작업 중 music-tag-filler만 잠시 중지하므로 먼저 사용자에게 중단 시간을 알리고 진행한다.
권한 오류가 나면 sudo/권한 변경으로 우회하지 않는다.

```sh
set -eu
umask 077
task_backup_dir="/volume3/backups/music-tag-filler-v6/$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$task_backup_dir"
cd "$task_backup_dir"
test "$(docker inspect --format '{{.State.Running}}' music-tag-filler)" = true
trap 'docker start music-tag-filler >/dev/null' EXIT
docker stop music-tag-filler
docker cp music-tag-filler:/data - > data.tar
docker inspect music-tag-filler > container-inspect.json
docker cp portainer:/data/compose/32/docker-compose.yml - > portainer-definition.tar
docker image save -o image.tar music-tag-filler-nas:v2.0.0
sha256sum data.tar image.tar container-inspect.json portainer-definition.tar > SHA256SUMS
sha256sum -c SHA256SUMS
tar -tf data.tar | head -20
docker start music-tag-filler >/dev/null
trap - EXIT
test "$(docker inspect --format '{{.State.Running}}' music-tag-filler)" = true
# 실패 시 EXIT trap으로 재시작을 시도하며, 시작 실패는 즉시 수동 확인한다.
```

`data.tar`에는 data 전체가 들어가므로 키·개인 파일명·가사·음악 원본 바이트를 포함할 수 있다.
이 백업을 **GitHub Release/Actions artifact/저장소에 업로드하지 않는다**.
완성된 백업을 다른 장치로 복제하고 암호화한다. SSH 개인키는 이 NAS 백업에 자동 포함되지 않는다.
tar 목록이 기대한 `data/` 구조인지 직접 확인한다. Portainer archive는 실제 정의의 사본이며 편집하지 않는다.

프로그램은 중지해도 다른 음악 관리 프로그램의 쓰기까지 중지하지는 않는다.
음악/sidecar는 NAS 스냅샷 등으로 동일 시점에 별도 보관한다.

## 새 NAS 또는 손상된 data 복구

1. 백업을 읽을 수 있는 독립 장치에서 가져오고 `sha256sum -c SHA256SUMS`를 통과시킨다.
2. 기존 운영 data에 바로 압축을 풀지 않는다. 비어 있는 별도 복구 디렉터리에 data.tar를 풀어 확인한다.
   압축 항목이 `data/` 아래인지, 절대 경로·`..`·예상 밖 링크가 없는지 먼저 검사한다.
3. 필요한 경우 `tar --no-same-owner -xpf <data.tar> -C <새복구디렉터리>`로 복원한다.
   소유권/ACL 오류는 보고하고 임의의 광범위 권한 변경을 하지 않는다.
4. jobs/settings JSON을 파싱할 수 있는지, backups의 manifest/원본 파일들이 모두 있는지 확인한다.
   manifest.sha256은 manifest.json의 SHA256 값이며 일반적인 `sha256sum -c` 목록 형식이 아니다.
   `original.bin` 해시/크기는 manifest와 같아야 한다. 손상 시 저장/복원 차단을 유지한다.
5. 기존 설치라면 music-tag-filler를 중지하고 현재 data를 **다른 이름으로 보존한 뒤** 검증한 복원 data로 교체한다.
   새 설치라면 프로그램을 처음 실행하기 전에 프로젝트의 `data/` 위치에 복원한다.
6. 같은 버전의 이미지를 복원하거나 Git 소스로 새 빌드한다.
   `docker image load -i <image.tar>`는 보관한 이미지/태그를 되살린다.
7. [설치 문서](INSTALL_KO.md)에 따라 음악과 복구 data를 승인된 읽기쓰기로 매핑하고 시작한다. 복구 확인 중에는 음악 저장을 실행하지 않는다.
   Portainer ID·IP·키 위치는 새 환경에 맞춘다. 예전 전체 inspect JSON을 임의 실행 설정으로 바꾸지 않는다.
8. HTTP·diagnostics·preferences·폴더 목록 확인 후에만 재개한다. 재시작된 진행 작업은 interrupted가 정상이다.
   경로가 유지되면 SHA256 기준 이어하기를 사용한다. 음악 상대 경로가 바뀌면 새 스캔이 필요할 수 있다.

**checksum이 맞는 archive와 실제 음악 원본의 의미적 일치는 별개**다.
기존 중앙 백업·옆 sidecar·음악 상대 경로가 서로 맞아야 프로그램의 되돌리기가 검증된다.
최초 백업을 재생성하거나 legacy 백업을 ‘정상’으로 표시하여 우회하지 않는다.

## 음악 태그 되돌리기와 재해 복구의 차이

P0 되돌리기는 검증된 최초 원본 전체 바이트를 복원하지만 음악 쓰기 권한이 필요하다.
현재 운영은 2026-10-21 사용자 요청으로 `/music:rw`이며 태그 저장·파일명 변경·되돌리기가 가능하다.
복구 절차에서 승인된 마운트 모드를 임의로 변경하지 않는다. 실제 음악 재해 복구는 NAS 백업 도구/관리 절차로 별도 수행한다.
저장·되돌리기의 앱 검증은 격리된 생성 음원에서만 한다.
태그만 들어 있던 옛 백업에는 잃어버린 원본 바이트가 없을 수 있어 완전 복원이 불가능하다.

## 백업 복구 훈련과 한계

최소한 독립 장치에서 archive를 읽고 빈 경로로 풀어 검사하는 훈련을 한다.
운영 data·음악을 연결하지 않은 별도 컨테이너에서 JSON/백업 형식과 시작을 확인한다.
훈련 날짜·이미지 ID·파일 수·checksum 결과·복구하지 못한 항목을 별도 사설 기록에 남긴다.
이번 준비 작업에서는 운영 중지·실제 data 백업·실제 archive 복구를 실행하지 않았다.

명령 근거: [Docker cp](https://docs.docker.com/reference/cli/docker/container/cp/),
[이미지 저장](https://docs.docker.com/reference/cli/docker/image/save/),
[이미지 복원](https://docs.docker.com/reference/cli/docker/image/load/).


직접 파일명 변경을 사용한 경우 data의 renames 기록도 jobs.json·backups와 함께 보존합니다. [파일명 변경 복구](FILENAME_RENAME.md)를 참고하세요.


## 선택적 시간 가사 저장의 복구 기록

SYLT는 MP3 ID3v2.3에 명시된 밀리초만 저장하고 USLT를 함께 유지합니다. LRC 생성은 기본 비활성이며 기존 LRC를 덮어쓰지 않습니다. `data/lyric-assets` 의도 기록도 `jobs.json`·`backups`·`renames`와 함께 보존합니다. 서버 시작 시 음악 SHA256과 기록을 대조해 완료된 음악 저장의 LRC 생성을 이어서 처리하고, 불명확한 상태는 쓰기를 차단합니다.

앱에서 파일명을 바꾸면 연결된 LRC도 덮어쓰기 없는 이름 변경과 복구 기록으로 이동합니다. 최초 원본 복원은 기존 정책대로 음악 파일 전체 바이트를 복원하며, 별도 LRC는 삭제하거나 덮어쓰지 않습니다. 음악 원본 복원 후 LRC가 남는 것은 이 보존 정책에 따른 동작입니다.
