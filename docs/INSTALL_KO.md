# 신규 설치 및 PC·NAS 교체

현재 환경의 정확한 값은 [CURRENT_NAS.md](CURRENT_NAS.md), 데이터 복구는
[BACKUP_RESTORE_KO.md](BACKUP_RESTORE_KO.md)를 먼저 읽는다.
아래 명령은 **나중에 사용자가 설치를 요청했을 때** 실행할 절차다. 이번 문서 작성 중에는 실행하지 않았다.

## 1. 소스 확보와 준비물

- GitHub 대상 저장소는 비공개여야 한다. 인증은 Git Credential Manager/브라우저로 한다.
  비밀번호·토큰을 clone URL이나 문서에 붙이지 않는다.
- Windows: Git, OpenSSH(`ssh`, `scp`), PowerShell 5.1 이상, 테스트용 Node.js 24.
- NAS: Docker와 Compose, 선택적으로 Portainer. 현 NAS는 Linux x86_64이다.
- 인터넷: Docker 기반 이미지·Debian·PyPI 다운로드와 음악 검색 API 조회에 필요.
- 음악 원본과 프로그램 data는 GitHub에 없으므로 별도 백업에서 확보해야 한다.

대상 폴더가 이미 있으면 덮어쓰거나 `.git`를 새로 만들지 않는다.

```powershell
git clone https://github.com/SoonCheol/music-tag-filler-nas.git C:\Codex\music-tag-filler-nas
Set-Location C:\Codex\music-tag-filler-nas
git status
git log -5 --oneline
Copy-Item .\deploy-nas.example.json .\deploy-nas.local.json
```

로컬 JSON은 현재 환경표로 채운다. GitHub 저장소에 최신 소스가 commit·push되어
있어야 이 절차로 복구할 수 있다. 아직 업로드하지 않은 작업 파일은 clone으로 복구되지 않는다.

## 2. SSH와 NAS 권한

NAS SSH를 활성화하고 작업 계정으로 프로젝트 디렉터리와 Docker를 사용할 수 있는지 확인한다.
기존 개인키는 별도 암호화 백업에서 복원한다. 없으면 새 키를 만들고 **공개키만** NAS 계정에 등록한다.
개인키/암호는 Git에 넣지 않으며 `authorized_keys`의 다른 키를 덮어쓰지 않는다.
새 서버/PC의 첫 SSH 연결에서는 NAS에서 확인한 호스트 키 지문과 비교한 후 신뢰한다.
`StrictHostKeyChecking=no` 또는 권한 우회는 사용하지 않는다.

```powershell
ssh -i C:\Users\homes\.ssh\codex_nas hitmyhead@192.168.0.100 whoami
ssh -i C:\Users\homes\.ssh\codex_nas -o BatchMode=yes hitmyhead@192.168.0.100 "docker version"
```

경로·계정은 새 PC/NAS 값으로 치환한다. 암호화 개인키는 사전에 SSH 에이전트에
등록해야 BatchMode 자동 배포가 가능하다. sudo 암호나 Docker 권한 오류가 나면 중단하고
사용자에게 실제 필요한 권한을 보고한다. 권한을 임의로 변경하지 않는다.

## 3. NAS에 최초 소스 설치

이 단계는 **아직 music-tag-filler 컨테이너가 없는 새 설치 전용**이다. 기존 설치는 업데이트 절차를 사용한다.
음악 경로가 존재하고 읽을 수 있는지, 8000 포트가 비어 있는지 확인한다.
없는 음악 경로를 빈 폴더로 만들어 문제를 숨기지 않는다.
이전 data가 있다면 새로 만들기 전에 별도 복구 절차를 진행한다.

```powershell
ssh -i C:\Users\homes\.ssh\codex_nas -o BatchMode=yes hitmyhead@192.168.0.100 "mkdir -p /volume3/docker3/music-tag-filler-v6/data"
scp -O -r -i C:\Users\homes\.ssh\codex_nas -o BatchMode=yes app Dockerfile requirements.txt requirements.lock.txt .dockerignore portainer-stack.yml hitmyhead@192.168.0.100:/volume3/docker3/music-tag-filler-v6/
ssh -i C:\Users\homes\.ssh\codex_nas -o BatchMode=yes hitmyhead@192.168.0.100 "cd /volume3/docker3/music-tag-filler-v6 && docker build -t music-tag-filler-nas:v2.0.0 ."
```

`scp -O`는 기존에 검증된 legacy SCP 방식이다. 개인키·로컬 JSON·Git 메타데이터·음악은 전송하지 않는다.
`requirements.lock.txt`는 검증된 NAS의 Python 패키지 31개 버전 제약이며 Dockerfile이 이를 사용한다.
기반 `python:3.11-slim`과 Debian 패키지는 고정 digest/버전이 아니므로 완전히 동일한 이미지
바이트를 재현하려면 별도 보관한 이미지 tar를 `docker image load`로 복구해야 한다.

## 4. Portainer 스택 생성

1. Portainer의 NAS Docker 환경에서 새 스택 이름을 **`music-tag-filler`**로 지정한다.
2. 저장소 루트 `portainer-stack.yml`을 Web editor에 넣는다. 먼저 NAS에서 위 이미지를 빌드해야 한다.
3. 새 NAS의 음악/data 호스트 경로를 확인한다. 현재 승인된 운영 설정은 음악 `read_only: false`이다. 읽기 전용 운영을 원하면 YAML을 true로 설정하고 로컬 JSON의 MusicReadOnly도 true로 맞춘다.
4. 스택을 생성하고 컨테이너가 하나만 생성되는지 확인한다. 메모리·권한·환경변수를 임의 추가하지 않는다.
5. 실제 Portainer Compose 파일 위치를 확인하여 `deploy-nas.local.json`의 `PortainerStackFile`에 기록한다.

Portainer를 쓰지 않는 설치에 한해서 다음 CLI 경로도 가능하다.
이 경우 자동 배포에는 `-RemoteComposeFile /volume3/docker3/music-tag-filler-v6/portainer-stack.yml`을
명시해야 한다. Portainer 관리 스택과 CLI 스택을 동시에 만들지 않는다.

```sh
cd /volume3/docker3/music-tag-filler-v6
docker compose -p music-tag-filler -f portainer-stack.yml up -d --no-build --pull never
```

기존 Portainer 설치에 저장소 YAML을 다시 적용하는 것은 업데이트 방법이 아니다.
자동 배포는 기존 실제 정의를 읽고 설정 동일성을 검증하여 music-tag-filler만 재생성한다.

## 5. 설치 확인

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-nas.ps1 -CheckOnly
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-nas.ps1 -PreflightOnly
Invoke-RestMethod http://192.168.0.100:8000/api/diagnostics
Invoke-RestMethod http://192.168.0.100:8000/api/preferences
```

웹 HTTP 200, 폴더 목록, `/music`의 RW=true, `/data`의 RW=true를 확인한다.
확인을 위해 운영 스캔·저장을 시작하지 않는다. `/music:rw`에서는 음악 태그 저장·이름 변경·되돌리기가
가능하므로 원본 백업이 중요하다. 저장 검증은 테스트용 음원과 격리된 임시 디렉터리에서 한다.

AcoustID는 키 없이 실제 조회할 수 없다. 발급한 애플리케이션 키를 기존 data의
`acoustid_key.txt`에 별도 저장하면 다음 조회부터 읽는다. 키를 저장소·Stack YAML에 넣지 않는다.
키 미설정은 오류 우회 대상이 아니며 텍스트 검색은 사용할 수 있다.

## 6. 교체 후 변경할 항목

새 NAS/PC에서는 로컬 JSON의 주소·계정·키 경로·프로젝트·Portainer ID·웹 주소,
두 YAML의 음악/data 경로, `CURRENT_NAS.md`를 함께 갱신한다.
옛 NAS와 새 NAS가 같은 data 또는 음악을 동시에 쓰지 않도록 한다.
새 서버의 Docker·CPU 차이에 대해서는 격리 회귀 테스트와 preflight를 다시 통과시킨다.
필요한 계정·키·음악·data 백업이 없다면 GitHub 소스만으로 그 내용을 복원할 수 없다.

## 개인 경로 없는 신규 설치 예시

운영과 분리된 신규 Compose 설치는 [README의 설치 예시](../README.md)와 루트 compose.example.yml을 따른다. 기존 운영 설치에는 적용하지 않는다. .env.example은 지원 변수 설명용이며 기존 Compose의 자동 입력 파일이 아니다.
