# 어디갈래

전국 161개 시·군별 관광지, 추천 코스(구간별 이동시간), 주변 맛집, 최신 여행 영상을 보여주는 여행 플래너.
GitHub Pages 웹앱으로 만들고, 그대로 안드로이드 앱(TWA)으로 감싸 구글 플레이스토어에 올린다.

```
index.html              앱 화면 전체 (HTML·CSS·JS 한 파일)
manifest.webmanifest    앱 이름·아이콘 (PWA)
sw.js                   오프라인 캐시
privacy.html            개인정보 처리방침 (플레이스토어 등록에 필요)
icons/                  앱 아이콘 192·512·마스커블
data/cities.json        전국 시·군 목록
data/cities/<id>.json   도시별 관광지·식당·영상·코스
data/cache/             설명·영상·코스 캐시 (API 호출 절약용)
scripts/collect.py      데이터 수집기 (TourAPI·YouTube·Claude)
scripts/make_sample.py  API 없이 화면 확인용 샘플 생성
.github/workflows/update-data.yml   매일 04:17 자동 수집
```

## 구조

```
GitHub Actions (매일)                         사용자 휴대폰
 ├ TourAPI   → 시·군 목록, 관광지, 음식점       어디갈래 앱(TWA)
 ├ 중심관광지 → 시·군별 인기 순위(관광지·맛집)
 ├ YouTube   → 관광지별 최신 영상 3~4편     →    = GitHub Pages 웹앱
 └ Claude    → 도시별 1일·1박2일 코스              data/*.json 읽어서 표시
        ↓ data/*.json 커밋                          ↓ 링크
                                              유튜브 · 인스타그램 · 카카오맵 길찾기
```

- 서버 없음. API 키는 전부 GitHub Secrets에만 있고 앱에는 들어가지 않는다.
- 이동시간은 직선거리 × 1.3 보정으로 추정(1.5km 이하 도보, 그 이상 차량). 각 구간의 "길찾기"를 누르면 카카오맵이 실제 대중교통·자동차 경로를 보여준다.
- 영상은 앱에 복사하지 않고 썸네일과 링크만 표시 → 누르면 유튜브로 이동. 인스타그램은 해시태그 페이지 링크.
- 특별·광역시는 시 전체를 한 도시로, 도는 시·군 단위로 묶는다.

## 1. 저장소 만들기

1. GitHub에서 새 저장소 생성 (예: `eodigallae`, Public)
2. 이 폴더의 파일 전부 업로드 (`.github` 폴더 포함)
3. Settings → Pages → Source: `Deploy from a branch`, Branch: `main` / `(root)` → 몇 분 뒤 `https://<아이디>.github.io/eodigallae/` 접속 확인

처음에는 원주·남원·전주 샘플 데이터로 열린다.

## 2. API 키 발급

| 키 | 어디서 | 비용 | 필수 |
|---|---|---|---|
| `TOURAPI_KEY` | 공공데이터포털 → "한국관광공사_국문 관광정보 서비스_GW" 활용신청 → 마이페이지의 **일반 인증키(Decoding)** | 무료 (개발계정 하루 1,000건, 운영계정 신청 시 상향) | 필수 |
| (같은 키) | 공공데이터포털 → "한국관광공사_지자체 중심 관광지 정보" **활용신청만** 추가 (키는 위와 동일) | 무료 | 권장 — 시·군별 인기 순위(T map 내비 검색 기반). 없으면 순위 없이 정렬 |
| `YOUTUBE_API_KEY` | Google Cloud Console → 프로젝트 생성 → YouTube Data API v3 사용 설정 → 사용자 인증 정보 → API 키 | 무료 (하루 10,000 unit = 검색 약 100회) | 선택 |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys | 사용량 과금 (도시당 코스 생성 1회, 30일마다 갱신) | 선택 |

YouTube 키가 없으면 사진을 눌렀을 때 유튜브 검색 결과로 연결되고, Claude 키가 없으면 가까운 관광지끼리 묶는 기본 코스가 만들어진다.

## 3. 키 등록 후 첫 수집

1. 저장소 Settings → Secrets and variables → Actions → New repository secret 으로 위 키 이름 그대로 등록
2. Actions 탭 → "데이터 갱신" → Run workflow
   - 첫 실행은 `cities`에 `원주시,남원시,전주시` 를 넣어 결과를 먼저 확인
   - 확인되면 비워두고 실행 → 매일 40곳씩 오래된 순으로 갱신, 약 5일이면 전국 한 바퀴
3. 첫 실수집이 끝나면 샘플 파일 삭제: `data/sample/`, `data/cities/jeonju.json`, `namwon.json`, `wonju.json`

하루 호출량(기본값): TourAPI 약 400~800건, YouTube 검색 최대 90회, Claude 최대 40회. `collect.py --help` 로 조정.

로컬에서 돌리려면:
```bash
pip install -r scripts/requirements.txt
export TOURAPI_KEY=... YOUTUBE_API_KEY=... ANTHROPIC_API_KEY=...
python scripts/collect.py --cities 원주시,남원시,전주시
python -m http.server 8000   # http://localhost:8000
```

## 4. 플레이스토어 출시

1. **개발자 계정**: Google Play Console 가입 (1회 25달러, 신분증 인증). 2023-11-13 이후 만든 개인 계정은 출시 전 **테스터 12명이 14일 연속 참여한 비공개 테스트**가 필수.
2. **앱 패키지 만들기**: pwabuilder.com 에 GitHub Pages 주소 입력 → Package for stores → Android → 패키지 ID(예: `io.github.<아이디>.eodigallae`) 입력 → `.aab` 파일과 서명 키, `assetlinks.json` 다운로드. **서명 키 파일은 반드시 따로 보관** (잃어버리면 업데이트 불가).
3. **도메인 연결(assetlinks)**: 앱 안에서 주소창 없이 보이려면 `assetlinks.json`이 도메인 최상위 `/.well-known/assetlinks.json`에 있어야 한다. 프로젝트 사이트(`<아이디>.github.io/eodigallae`)는 최상위가 아니므로
   - `<아이디>.github.io` 이름의 저장소를 하나 더 만들어 `.well-known/assetlinks.json`을 올리거나
   - 개인 도메인을 연결해 그 루트에 올린다.
4. **Play Console 등록**: 앱 만들기 → 비공개 테스트 트랙에 `.aab` 업로드 → 테스터 12명 이상 이메일 등록 → 14일 유지 → 프로덕션 액세스 신청.
5. **스토어 등록정보**: 앱 아이콘(`icons/icon-512.png`), 스크린샷, 설명, 개인정보처리방침 URL(`.../privacy.html`, 문의 이메일을 실제 주소로 바꿀 것), 데이터 보안 설문(수집하는 데이터 없음), 콘텐츠 등급 설문.

## 대표 명소 직접 고정하기

인기 순위는 T map 내비 검색 기반이라, 서울처럼 대중교통으로 많이 가는 곳(경복궁 등)은 순위가 낮게 나올 수 있다.
`data/curated.json`에 도시 이름과 명소를 적으면 그 순서대로 맨 앞에 고정되고 코스에도 우선 들어간다.
GitHub 웹에서 파일을 열고 연필(✏️) 버튼으로 바로 고칠 수 있다. 다음 수집 때 반영.

```json
"서울": ["경복궁", "창덕궁", "북촌한옥마을", "N서울타워"]
```

## 데이터 출처 표시

- 관광정보: 한국관광공사 TourAPI (공공누리, 출처 표시) — 화면 하단에 표시됨
- 영상: YouTube API 서비스 — 앱은 YouTube 서비스 약관을 따르며 privacy.html에 고지
- 인스타그램은 API 수집 없이 해시태그 링크만 제공 (Meta 약관상 자동 수집 금지)

## 다음 단계 후보

- 사용자가 날짜·취향을 넣으면 그 자리에서 코스를 짜주는 기능 (API 키를 숨길 작은 서버 필요: Cloudflare Workers 등)
- ODsay 대중교통 API로 구간별 실제 소요시간 (수집 단계에서 코스 구간만 미리 계산)
- 축제 정보 (TourAPI `searchFestival2`)
- 인스타그램 해시태그 API (비즈니스 계정 + Meta 앱 심사 필요, 7일에 해시태그 30개 제한)
