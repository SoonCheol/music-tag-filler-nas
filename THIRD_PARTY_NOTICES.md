# 타사 코드·실행 도구 라이선스

## 재사용한 원본 소스

`app/upstream/`는 `microhan1/music-tag-filler`의 커밋
`8996e2daa74c787395ebbf3f9d871b1484f4aafe`에서 가져온 MIT 코드다.
저작권자 표기와 원문은 [LICENSE](app/upstream/LICENSE), 변경 범위는
[NOTICE.md](app/upstream/NOTICE.md)에 보존했다. 재배포 시 이 두 고지를 제거하지 않는다.

원본 LICENSE 끝의 Windows `third_party/fpcalc.exe` 안내는 원문 일부다.
이 저장소는 그 exe를 포함하지 않는다. NAS에서는 Debian의 `libchromaprint-tools`를 설치한다.
Chromaprint LGPL-2.1 전문과 검증 이미지의 Debian 패키지 고지를 `licenses/`에 보관했다.

## 실행 시 설치되는 구성요소

| 구성요소 | 보관/참조 |
| --- | --- |
| Chromaprint/fpcalc | `licenses/Debian-Chromaprint-copyright.txt`, `licenses/LGPL-2.1.txt` |
| FFmpeg | `licenses/Debian-FFmpeg-copyright.txt`, `licenses/GPL-2.txt`, `licenses/GPL-3.txt`, LGPL 고지 |
| Python 패키지 | requirements.txt와 requirements.lock.txt에 이름/버전 보관. 설치된 각 배포판의 dist-info LICENSE/METADATA 유지 |
| Python/Debian 기반 이미지 | 해당 이미지와 설치 패키지의 고지 유지. Dockerfile은 공식 이미지와 Debian 저장소로 빌드 |

이 Git 저장소에는 FFmpeg·fpcalc·Python 패키지 바이너리나 제3자 음악/커버를 넣지 않는다.
현재 이미지에서 복사한 라이선스 스냅샷은 향후 버전의 라이선스를 대신하지 않는다.
의존성 변경 또는 Docker 이미지를 외부에 배포할 때는 실제 빌드의 고지·소스 제공 조건을 다시 확인한다.

추가 NAS 코드 전체에 적용할 별도의 최상위 라이선스는 아직 소유자가 지정하지 않았다.
원본 MIT를 프로젝트 전체의 임의 라이선스 선언으로 확대하지 않는다.
