# NAS 공통 업데이트 서비스

## 구성

Music Tag Filler 웹의 업데이트 메뉴 → 기존 앱 서버의 안전한 프록시 → 별도 NAS Update Agent → GitHub Actions/GHCR 및 Portainer.

하나의 Agent에서 여러 앱을 관리한다. 앱별 권한 키, GitHub 저장소/빌드 워크플로, 이미지 저장소, Portainer 스택·환경·서비스 ID, 안전 확인 URL을 허용 목록에 둔다. 앱은 자신의 상태만 볼 수 있으며 사용자 승인 전에는 설치하지 않는다.

**GitHub 구현과 실제 NAS 배포는 별개다.** 이 소스만 GitHub에 있다고 웹 업데이트가 바로 활성화되는 것이 아니다. 현재 NAS에 Agent가 실제 설치되어 있지 않거나 `NAS_UPDATER_*` 설정이 없으면 UI는 연결 실패로 표시한다.

## 사전 설정

1. GitHub Actions `.github/workflows/build-image.yml`이 검증을 통과해야 GitHub Container Registry에 변경 불가능한 `ghcr.io/sooncheol/music-tag-filler-nas:sha-<40자 커밋>` 이미지를 게시한다. 실패한 빌드는 업데이트 후보가 아니다. CI는 NAS를 건드리지 않는다.
2. Portainer에 비공개 GHCR 패키지를 받을 수 있는 **레지스트리 인증**을 별도로 설정한다. GitHub의 기존 `GITHUB_TOKEN`은 NAS에서 사용하는 토큰이 아니다. 패키지 읽기 범위의 자격증명 사용을 권장한다.
3. 별도의 업데이트 서비스에만 Portainer API 키와 GitHub Actions 조회 전용 읽기 토큰을 제공한다. 앱이나 브라우저에 전달하지 않는다. 별도 업데이트 관리자 암호는 사용하지 않으며 기존 Authelia 로그인을 유지한다.
4. 앱별로 고유한 길고 임의적인 인증 키를 생성한다. Agent에는 `UPDATER_APP_KEYS_JSON` 환경변수로, Music Tag Filler에는 같은 키 하나를 `NAS_UPDATER_KEY`로 제공한다. 저장소와 공개 웹페이지에는 어떤 비밀값도 입력하지 않는다.
5. 기존 포테이너 스택(#32, 환경 ID 7)의 실제 상태와 네트워크 이름을 확인한다. `updater.compose.example.yml`은 별도 Agent 스택을 설치하기 위한 **참고 파일**이다. 현재 Music Tag Filler의 스택 YAML과 바꿔치기하지 않는다. 외부로 8766 포트를 개방하지 않는다.
6. 별도 Agent를 동일 Docker 네트워크에 설치한 뒤 Music Tag Filler 스택의 환경변수에 아래 세 항목만 추가한다. Portainer 스택의 음악/설정 볼륨, 포트, 네트워크, 기존 환경변수를 보존한다.

   - `NAS_UPDATER_URL=http://nas-updater-agent:8766`
   - `NAS_UPDATER_APP_ID=music-tag-filler`
   - `NAS_UPDATER_KEY=<해당 앱의 인증 키>`

7. Agent의 `updater_agent/apps.example.json` 예시에서 스택/환경/서비스/음악 앱 내부 주소가 실제값과 일치하는지 확인한다. 다른 앱은 앱마다 항목을 추가한다. 다른 앱의 코드는 별도로 연결해야 한다.

## 작동

- **업데이트 확인:** Portainer가 현재 보관한 실제 Compose 이미지와 GitHub Actions에서 **성공한 최신 배포 빌드의 커밋 SHA**를 비교해 표시한다. 여기서 표시는 `v2.0.0` 같은 시맨틱 버전이 아니라 빌드 식별자다.
- **업데이트 실행:** 사용자가 업데이트 실행 버튼을 누르고 확인창에서 승인하면 설치를 요청한다. 별도의 암호 입력은 없다. 내부 앱 인증 키, 예상 이미지와 SHA가 맞지 않으면 중단한다.
- **변경 내용:** Agent는 지정된 단일 서비스 스택에 대해서만, 현재 Compose 원문에서 해당 이미지 한 줄만 바꾼다. YAML 재파싱 후 다른 필드가 달라졌다면 거절한다. `Env`는 Portainer에 저장된 기존 값을 그대로 사용하며 `PullImage=true`, `Prune=false`를 지정한다. 변경 전 Compose와 환경값은 Agent의 `/state`에 비공개 사본으로 남긴다.
- **작업 중 차단:** 실제 업데이트 바로 직전에 앱에서 검색/스캔·음악 저장·이름 변경 작업이 진행 중인지 검사한다. 확인 실패나 업데이트 중 다른 작업 발견 시 보수적으로 중단한다.
- **결과 표시:** 상태/실패 메시지를 표시한다. 실패한 경우 **자동 롤백하지 않는다.** 데이터 형식 호환성을 확인한 후 보관된 Compose와 이미지로 별도 복구한다.
- **보안:** 앱에는 GitHub/Portainer 관리자 키를 두지 않는다. 기존 Authelia 인증을 통과해 웹에 접속하고, 실행 API(/api/updater/apply)도 같은 인증 프록시의 보호를 받도록 유지한다. Agent는 외부에 공개하지 않으며, 앱별 인증 키 검사·스택 허용 목록·백업 및 작업 중 차단은 그대로 유지한다.

## 재사용 조건과 제한

다른 NAS 앱도 동일 구조를 재사용하려면 Agent 허용 목록의 새로운 앱 ID·컨테이너 이미지·스택 ID·환경 ID·서비스·GitHub Actions 워크플로·안전 확인 엔드포인트를 등록하고, 해당 앱에 업데이트 화면/프록시를 연결하면 된다. **한번 만든 Agent를 앱마다 다시 만들 필요는 없다.**

기본 구현은 파일 기반 Portainer의 **단일 서비스 Compose 스택**과 성공 빌드의 GHCR 태그에 한한다. 다중 서비스 스택·GitOps 스택·별도 패키지 형식·오디오 파일 저장 중 재시작은 자동 변경 대상이 아니다.

## 검증과 배포

소스의 `updater_agent/test_service.py`는 외부 네트워크 없이 이미지 이외 설정 불변, 스택 일치·복수 서비스 차단, 인증 비교, 스냅샷과 환경값 보존을 시험한다. GitHub CI는 Docker에서 이 테스트와 기존 앱 회귀 검사에 통과한 뒤에만 GHCR로 이미지를 발행한다.

최초 운영 적용은 별도 허가 하에 실제 Portainer 접속 방식/스택 원문을 읽은 후 진행한다. 기존 `/volume1/Multimedia/Music:/music:rw`, `/volume3/docker3/music-tag-filler-v6/data:/data`, 포트 `8000:8000`, 기존 환경변수와 접근 정책을 보존해야 한다. 운영 음원은 테스트나 업데이트를 이유로 수정·백업·삭제하지 않는다. Portainer에서 private GHCR 접근권한/실제 API 응답까지 검증해야 웹 설치가 동작한다고 확정할 수 있다.
