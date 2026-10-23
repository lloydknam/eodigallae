# 어디갈래 도우미 서버 (Cloudflare Workers)

앱의 **영상 그대로 여행**(유튜브 링크 → 코스)과 **숨은 핫플 제보**를 처리하는 작은 서버예요. 무료 범위(하루 10만 요청)로 충분해요.

1. dash.cloudflare.com 가입 → Workers & Pages → Create → Worker → 이름 `eodigallae` → Deploy
2. Edit code → `worker.js` 내용을 통째로 붙여넣기 → Deploy
3. Settings → Variables and Secrets → Add (Type: Secret)
   - `YOUTUBE_API_KEY`, `KAKAO_REST_KEY` (GitHub Secrets에 넣은 것과 같은 값)
   - `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (제보를 받을 텔레그램 봇)
4. 주소(`https://eodigallae.<내아이디>.workers.dev`)를 index.html의 `const WORKER = ""`에 넣기

카카오 정책에 따라 장소 좌표·주소는 저장하지 않고, 요청마다 실시간으로 조회해 돌려줘요.
