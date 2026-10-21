# 보안 검사 결과와 후속 조치

## 비밀값·업로드 경계

2026-10-21 작업 트리의 업로드 후보를 검사했다. 개인키 본문·실제 GitHub/API 토큰·
클라우드 키·인증 URL, 음악/상태/원본 백업 파일은 발견되지 않았다.
단순 키워드 검사에서 보이는 `err_acoustid_key`는 오류 코드이며 테스트의
`example.invalid` 인증 URL과 fixture 키는 실제 자격증명이 아니다.
검사는 비밀값 부재를 수학적으로 보장하지 않으므로 commit 전 diff도 검토한다.

사용자 요청에 따라 NAS 주소·계정·실제 경로·개인키 **위치**를 CURRENT_NAS.md와
운영 YAML에 의도적으로 보관한다. 비공개 저장소에서만 취급하며 공개 배포하지 않는다.
개인키 **내용**, 비밀번호, 실제 API 키, 음악, settings/jobs/data, 원본 백업은 제외한다.
로컬 JSON이 Git에서 제외되는 것도 확인했다. 과거 Git 기록은 삭제하지 않았다.

## Python 의존성 보안 공지

현재 NAS의 31개 패키지 잠금을 [OSV batch API](https://google.github.io/osv.dev/post-v1-querybatch/)에
이름/버전만 보내 조사했다. NAS 주소·키·파일명·음악 데이터는 보내지 않았다.
전체 응답을 정리한 스냅샷은 [dependency-audit.json](dependency-audit.json)에 보관했다.

| 패키지 | 현재 버전 | 일치한 공지 레코드 수 | 대표 공지 |
| --- | --- | --- | --- |
| Pillow | 10.3.0 | 43 | [폰트 이미지 경로의 크기 검사 우회](https://osv.dev/vulnerability/GHSA-45hq-cxwh-f6vc) |
| python-multipart | 0.0.9 | 16 | [multipart 경계 처리 DoS](https://osv.dev/vulnerability/GHSA-59g5-xgcq-4qw3) |
| Requests | 2.31.0 | 6 | [.netrc 인증정보 관련 URL 처리](https://osv.dev/vulnerability/GHSA-9hjg-9r4m-mvj7) |
| Starlette | 0.36.3 | 14 | [multipart 파일 처리 DoS](https://osv.dev/vulnerability/GHSA-2c2j-9gv5-cj73) |

**4개 패키지, 79개 공지 레코드**가 일치했다. 같은 취약점의 GHSA/PYSEC 별칭이
중복될 수 있으므로 79개 독립 CVE라는 뜻은 아니다.
이것은 버전 기반 일치이며 현재 앱에서의 실제 악용 가능성 판정은 아니다.
Debian/FFmpeg/Chromaprint/기반 이미지 전체의 CVE 검사는 이번에 수행하지 않았다.

### 후속 우선순위

1. 인터넷 노출 전 별도 보안 개선 작업으로 FastAPI/Starlette·python-multipart의
   호환 버전 조합, Pillow, Requests를 검토하고 P0/P1/P2 전체 회귀를 다시 수행한다.
   특정 대표 공지의 fixed 버전 하나만 올려 모든 공지가 해결됐다고 판단하지 않는다.
2. 앱은 이미지 검증을 하지만 해당 패키지의 모든 취약점을 대신 막는다고 보장할 수 없다.
3. 잠금 파일은 현재 정상 작동 환경의 재현을 위해 만들었다. ‘안전한 최신 버전 목록’이 아니다.
   이번 작업에서는 운영 의존성 업그레이드나 NAS 재배포를 하지 않았다.

재검사 명령(외부 네트워크 사용):

```powershell
node tools/audit_dependencies.js --online --output docs/dependency-audit.json
```

이 검사 도구는 결과를 기록할 뿐 취약 버전을 자동 설치/변경하지 않는다.

## 서비스 접근·복구 한계

현재 FastAPI 코드에는 별도 로그인/인증 의존성이 없으며 현 웹 주소는 HTTP다.
음악은 읽기 전용이지만 API는 작업/후보 조회와 설정 변경을 제공한다.
별도 인증 없이 인터넷에 공개하지 않는다. 외부 접근이 필요하면 사용자가 승인한
인증·TLS 프록시 구성을 별도 설계하고 검증한다. 실제 공유기/프록시의 외부 노출 상태는 조사하지 않았다.

GitHub 인증·비공개 상태·Actions 실행은 이번 작업에서 검증하지 않았다.
추가 NAS 코드 전체의 최상위 배포 라이선스도 소유자가 아직 지정하지 않았다.
운영 data/음악/비밀키 archive는 GitHub에 없으므로 별도 암호화 백업이 필요하다.
