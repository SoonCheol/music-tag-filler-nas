
# 음악 정보 채우기 NAS Web v0.3.0 - DXP4800+ 전용

원작: microhan - 음악 정보 채우기 v0.2.3 (Windows exe)
이식: Ugreen DXP4800+ Docker, 한국어 UI, 드래그 없음, 백그라운드 지속 스캔

## 왜 새로 만들었나
- music-tag-web은 중문 기반, UI/검색 품질 불만족으로 제외
- 원작의 핵심 안전규칙 그대로 유지 필요:
  - MusicBrainz + iTunes KR → US 폴백 교차조회
  - AcoustID 음향 지문 (fpcalc, 파일 업로드 없음)
  - LRCLIB 가사 - "틀린 가사보다 빈 가사가 낫다" 4원칙
  - 빈칸만 채우기, 90점 이상 자동 지정, 커버 1000px JPEG
  - .tagbak.json 바이트 단위 백업 + 되돌리기

## 기능 (드래그 제외)
1. **폴더 브라우저**: /music 하위 폴더 목록에서 선택, 직접 경로 입력도 가능
2. **백그라운드 스캔**: FastAPI BackgroundTasks + jobs.json 영구 저장. 브라우저 닫아도 NAS에서 계속, 재접속 시 /api/jobs 로 진행률 복구
3. **후보 표**: 제목/가수/앨범/연도/출처/일치도. 작은 커버 hover 시 300px 미리보기 (원작 동일)
4. **표지**: 파일 고르기 또는 후보 클릭으로 적용. 일괄 적용 후 전체 저장
5. **가사**: LRCLIB, 옵션 켜면 저장 시에만 시도. 서버 바쁨이면 "서버가 바빠 찾지 못함" 표시, 재저장 시 재시도
6. **저장**: /data/backups 에도 백업 복사본, 되돌리기는 .tagbak.json 기반

## 설치 - Ugreen DXP4800+

### SSH 1회
```
mkdir -p /volume3/docker3/music-tag-filler-nas/data
cd /volume3/docker3/music-tag-filler-nas
# 파일 업로드 후
docker compose up -d --build
```

### Portainer
Stacks > Add Stack > Name: music-tag-filler
Build method: Upload > docker-compose.yml 업로드
또는 Web editor에 위 compose 붙여넣기

접속:
- 로컬: http://192.168.0.100:8000
- NPM: nas.homedisk.net
  - Proxy Host: tag.homedisk.net
  - Forward: 192.168.0.100:8000
  - Websockets ON
  - SSL: Cloudflare 인증서

## 사용법 (NAS)
1. 웹 접속 > 📁 버튼으로 폴더 선택 (예: Trot/ 또는 빈칸=전체)
2. 체크: [x] 빈칸만 채우기(안전) [ ] 가사도 채우기 [ ] 파일명도 바꾸기
3. 스캔 시작 → "백그라운드 스캔 시작" 알림. 창 닫아도 됨
4. 재접속 > 오른쪽 하단 백그라운드 작업에서 진행률/현재 파일 확인
5. 후보 클릭 → 오른쪽 필드/왼쪽 커버에 적용
6. 저장 또는 전체 저장 → /volume1/Multimedia/Music 에 직접 쓰기

## AcoustID 키
원작 exe에는 키 내장. 이 Docker는 무료 키 필요:
1. https://acoustid.org/new-application 에서 API Key 발급
2. docker-compose.yml environment에 ACOUSTID_API_KEY 추가 (현재 코드는 키 없이도 텍스트 검색으로 동작)

## 백업
- 모든 저장은 원본을 .tagbak.json으로 남김
- /volume3/docker3/music-tag-filler-nas/data/backups 에도 복사
- 스냅샷 있는 상태에서 테스트 권장

## 로그
```
docker logs music-tag-filler-nas -f
```
