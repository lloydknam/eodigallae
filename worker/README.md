# 어디갈래 도우미 서버 (Cloudflare Workers)

앱의 **영상 그대로 여행**(유튜브 링크 → 코스)과 **숨은 핫플 제보**를 처리하는 작은 서버예요. 무료 범위(하루 10만 요청)로 충분해요.

1. dash.cloudflare.com 가입 → Workers & Pages → Create → Worker → 이름 `eodigallae` → Deploy
2. Edit code → `worker.js` 내용을 통째로 붙여넣기 → Deploy
3. Settings → Variables and Secrets → Add (Type: Secret)
   - `YOUTUBE_API_KEY`, `KAKAO_REST_KEY` (GitHub Secrets에 넣은 것과 같은 값)
   - `SEOUL_API_KEY` (열차지도 실시간용, GitHub Secrets에 넣은 서울 열린데이터광장 인증키와 같은 값)
   - `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (제보를 받을 텔레그램 봇)
4. 주소(`https://eodigallae.<내아이디>.workers.dev`)를 index.html의 `const WORKER = ""`에 넣기

카카오 정책에 따라 장소 좌표·주소는 저장하지 않고, 요청마다 실시간으로 조회해 돌려줘요.

## 열차지도 실시간 연결

1. 위 3번에서 `SEOUL_API_KEY`를 등록하고 Deploy
2. `https://eodigallae.<내아이디>.workers.dev/subway` 를 열어 `{"at":…,"trains":[…]}` 가 나오는지 확인
3. `subway-map.html` 위쪽의 `var WORKER = ""` 에 워커 주소를 넣고 커밋 → 지하철 지도의 **실시간** 버튼이 켜져요

호출은 20초 동안 한 번만 하도록 묶어 두었어요(노선 9개 = 요청 9건). 서울시 일일 호출 제한은 인증키마다 다르니, 모자라면 `max-age=20`을 늘려 주세요.
