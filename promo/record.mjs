// 인파지도 홍보 영상: 실제 페이지를 휴대폰 화면 크기로 열고, 깜빡임을 프레임 단위로 찍어 mp4로 만든다.
// CSS 애니메이션을 1/4 속도로 늦춘 뒤 찍고, 프레임 길이를 원래 속도로 맞춰 매끄럽게 만든다.
import { chromium } from "playwright";
import fs from "fs";
import { execSync } from "child_process";

const URL = process.env.SITE || "http://localhost:8000/#crowd";
const SECONDS = +(process.env.SECONDS || 15), RATE = 0.25;
const CENTER = [37.5465, 126.986], ZOOM = 13;   // 앱 시작 화면과 같게
const dir = "promo/frames"; fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir, { recursive: true });

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, timezoneId: "Asia/Seoul", locale: "ko-KR" });
await p.goto(URL, { waitUntil: "networkidle" });
await p.waitForFunction(() => window.__crowdMap && document.querySelectorAll(".lv-pulse").length > 50, null, { timeout: 60000 });
await p.evaluate(([c, z]) => window.__crowdMap.setView(c, z, { animate: false }), [CENTER, ZOOM]);
// 스크린샷처럼: 지도 윗부분이 화면 위쪽(상단바 아래)에 오도록 스크롤
await p.evaluate(() => { const m = document.getElementById("hotmap"); window.scrollTo(0, m.getBoundingClientRect().top + window.scrollY - 175); });
await p.waitForLoadState("networkidle"); await p.waitForTimeout(2500);   // 지도 그림 다 받기
const cdp = await p.context().newCDPSession(p);
await cdp.send("Animation.enable"); await cdp.send("Animation.setPlaybackRate", { playbackRate: RATE });
const list = []; let i = 0; const t0 = Date.now(); let last = t0;
while ((Date.now() - t0) * RATE < SECONDS * 1000) {
  const f = `${dir}/f${String(i).padStart(4, "0")}.png`;
  await p.screenshot({ path: f });
  const now = Date.now(); list.push([f, ((now - last) * RATE) / 1000]); last = now; i++;
}
await b.close();
// 첫 프레임 길이는 다음 프레임 간격으로 대신
list[0][1] = list[1]?.[1] || 0.04;
fs.writeFileSync(`${dir}/list.txt`, list.map(([f, d]) => `file '${f.split("/").pop()}'\nduration ${d.toFixed(4)}`).join("\n") + `\nfile '${list.at(-1)[0].split("/").pop()}'\n`);
execSync(`ffmpeg -y -loglevel error -f concat -safe 0 -i ${dir}/list.txt -vf "fps=30,format=yuv420p" -c:v libx264 -crf 20 -preset slow -movflags +faststart promo/crowd-map.mp4`, { stdio: "inherit" });
console.log("frames", list.length, "→ promo/crowd-map.mp4");
