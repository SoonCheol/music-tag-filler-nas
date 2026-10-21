> 레거시 설치 예시 문서입니다. 주소·경로는 예시이며, 현재 v6 자동 배포는 [DEPLOYMENT.md](DEPLOYMENT.md)를 따릅니다.


# 음악 정보 채우기 - NAS Docker Web 버전

원작: microhan - 음악 정보 채우기 v0.2.3 (Windows)
웹 변환: Ugreen DXP4800+ 전용, 백그라운드 스캔, 재접속 진행률 유지, 저장/되돌리기

## 특징 (원작 로직 그대로 이식)
- 텍스트 검색 + 음향 지문(AcoustID fpcalc) : MusicBrainz + iTunes Store API 교차 조회, 점수 순 정렬
- 커버: Cover Art Archive + iTunes 고화질, 긴 변 1000px JPEG 리사이징
- 포맷: MP3, FLAC, M4A, OGG
- 안전 규칙: 90점 이상 자동 지정, 빈칸만 자동 채우기, 기존 앨범/연도/표지는 수동 승인만 변경
- 백업: 저장 직전 `원본파일명.tagbak.json` + /data/backups 에 복사, 1바이트 복구
- 가사: LRCLIB(lrclib.net), 원칙 "틀린 가사보다 빈 가사가 낫다" - 아티스트 일치, 버전표시 일치, 길이 ±3초, 중복 가사 일치, Instrumental 제외, plain만
- 파일명 정리: `가수 - 제목` 형식
- 백그라운드: 스캔은 FastAPI BackgroundTasks, jobs.json에 상태 저장 → 웹 닫아도 계속, 재접속시 /api/jobs로 진행률 복구

## Ugreen NAS 설치

### 1. 폴더 구조
/srv/docker/music-tag-filler-nas/
  ├── Dockerfile
  ├── docker-compose.yml
  ├── requirements.txt
  └── app/
      ├── main.py
      └── static/index.html

/srv/docker/music-tag-filler-nas/data/  ← 자동 생성

### 2. Portainer 배포
Portainer > Stacks > Add Stack > Build method: Repository 또는 Upload
portainer-stack.yml 붙여넣기, Build and deploy

또는 SSH:
```
cd /srv/docker/music-tag-filler-nas
docker compose up -d --build
```

### 3. 접속
- 로컬: http://nas.example.invalid:8000
- NPM: nas.example.invalid 도메인 추가
  - Domain: tag.example.invalid (또는 nas.example.invalid/tag/)
  - Forward Hostname: nas.example.invalid
  - Forward Port: 8000
  - Websockets Support ON
  - Cloudflare SSL

### 4. 사용법
1. 웹 접속 > 스캔 경로 입력 (비우면 전체)
2. 옵션: 빈칸만 채우기(권장), 가사도 채우기, 파일명 바꾸기 체크
3. 스캔 시작 → 백그라운드로 진행, 브라우저 닫아도 OK
4. 다시 접속 > 백그라운드 작업 카드에서 진행률/현재 파일 확인
5. 결과 표에서 후보 클릭 > 왼쪽 미리보기 + 오른쪽 태그 필드에 적용
6. 표지 hover 시 300px 큰 미리보기 (원작 기능)
7. 저장 버튼 → /music에 직접 쓰기 + .tagbak.json 백업

## 이미 검증된 대안 (바로 쓸 수 있음)
FuZhouhao/music-tag-web — NAS 최적화, Docker Hub에 이미 빌드됨
```
docker pull xhongc/music_tag_web:latest
docker run -d -p 8002:8002 -v /srv/music:/app/media:rw -v /srv/docker/music-tag-web/data:/app/data --restart=always xhongc/music_tag_web:latest
```
접속: http://nas.example.invalid:8002/admin (인증 설정은 해당 제품의 공식 안내 참고)

## 안전 팁
- 처음엔 하위 폴더 하나만 테스트
- /srv/music 스냅샷 있으면 더 안전
- .tagbak.json 백업은 되돌리기용, 공유 금지 (가사 저작권)

## 개선 가능
- fpcalc 지문 정확도 높이기: pyacoustid 연동 이미 포함, 컨테이너에 fpcalc 바이너리 있음
- LRCLIB 서버 바쁨 처리: "서버가 바빠 찾지 못함" 상태 표시, 재저장시 재시도 (원작 동일)
