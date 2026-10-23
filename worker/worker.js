// 어디갈래 도우미 서버 (Cloudflare Workers, 무료 범위)
// 1) GET  /video?url=<유튜브 링크>  → 영상 속 장소를 찾아 좌표와 함께 돌려준다 (코스 만들기용)
// 2) POST /report                  → 숨은 핫플 제보를 텔레그램으로 전달한다
//
// 비밀값(Settings → Variables and Secrets):
//   YOUTUBE_API_KEY   유튜브 Data API 키
//   KAKAO_REST_KEY    카카오 REST API 키
//   TELEGRAM_TOKEN    (제보용) 텔레그램 봇 토큰
//   TELEGRAM_CHAT_ID  (제보용) 제보를 받을 채팅 ID
//
// 카카오 정책: 장소 좌표·주소는 저장하지 않고 요청 때마다 실시간으로 조회해 바로 돌려준다.

const SITE = "https://lloydknam.github.io";
const DATA = "https://lloydknam.github.io/eodigallae/data";

const cors = (origin) => ({
  "Access-Control-Allow-Origin": origin && origin.startsWith(SITE) ? origin : SITE,
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Vary": "Origin",
});
const json = (obj, status, origin) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json; charset=utf-8", ...cors(origin) } });

const norm = (s) => String(s || "").replace(/\(.*?\)|\[.*?\]/g, "").replace(/[^0-9A-Za-z가-힣]/g, "").toLowerCase();
const cityBase = (n) => n.replace(/(특별자치시|특별자치도|광역시|특별시|시|군)$/, "") || n;
const GENERIC = new Set(["카페", "맛집", "시장", "공원", "해변", "바다", "산책", "야경", "숙소", "호텔", "거리", "골목", "전망대", "박물관", "미술관", "핫플", "여행", "브이로그"]);
const NOT_PLACE = /^(인트로|intro|오프닝|아웃트로|outro|엔딩|ending|마무리|숙소|구독|좋아요|bgm|music|음악|광고|협찬|문의|출처|인스타|타임라인|목차|\d+일차|day\s?\d+|도착|출발|이동)/i;

function videoId(url) {
  const m = String(url).match(/(?:youtu\.be\/|v=|\/shorts\/|\/embed\/|\/live\/)([A-Za-z0-9_-]{11})/);
  return m ? m[1] : (/^[A-Za-z0-9_-]{11}$/.test(url) ? url : null);
}

// 영상 설명의 타임라인(01:20 장소)·핀(📍장소) 줄에서 장소 이름 후보
function extractNames(text) {
  const out = [];
  for (const line of text.split(/\n/)) {
    const m = line.match(/^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}\s*[-–—|~:]?\s*(.+)$/) || line.match(/^\s*(?:📍|📌|☕|🍽|▶|✔|\d+\.)\s*(.+)$/u);
    if (!m) continue;
    let t = m[1].split(/\s[-–—|/]\s|[:：(]|https?:\/\//)[0].replace(/[^\w\s가-힣&'·.]/g, " ").trim();
    if (t.length < 2 || t.length > 20 || NOT_PLACE.test(t) || GENERIC.has(norm(t))) continue;
    if (!out.some((x) => norm(x) === norm(t))) out.push(t);
  }
  return out.slice(0, 15);
}

async function kakaoSearch(env, query, near) {
  const u = new URL("https://dapi.kakao.com/v2/local/search/keyword.json");
  u.searchParams.set("query", query); u.searchParams.set("size", "5");
  if (near) { u.searchParams.set("x", near.lng); u.searchParams.set("y", near.lat); u.searchParams.set("radius", "20000"); }
  const r = await fetch(u, { headers: { Authorization: `KakaoAK ${env.KAKAO_REST_KEY}` } });
  if (!r.ok) return [];
  return (await r.json()).documents || [];
}

// 카카오 주소("전북특별자치도 전주시 완산구 …", "서울 중구 …")로 우리 도시 찾기
function cityOfAddress(cities, addr) {
  const t = String(addr || "").split(/\s+/);
  if (!t[0]) return null;
  const sameProv = (c) => c.province.slice(0, 2) === t[0].slice(0, 2);
  return cities.find((c) => c.province === c.name && sameProv(c))            // 특별·광역시
      || cities.find((c) => c.name === t[1] && sameProv(c))
      || cities.find((c) => c.name === t[1]) || null;
}

async function handleVideo(env, url) {
  const id = videoId(url);
  if (!id) return { error: "유튜브 영상 링크를 확인해 주세요." };
  const yr = await fetch(`https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&id=${id}&key=${env.YOUTUBE_API_KEY}`);
  if (!yr.ok) return { error: "유튜브 정보를 가져오지 못했어요. 잠시 뒤 다시 해 주세요." };
  const v = ((await yr.json()).items || [])[0];
  if (!v) return { error: "영상을 찾지 못했어요. 공개 영상인지 확인해 주세요." };
  const sn = v.snippet || {};
  const text = [sn.title || "", sn.description || "", (sn.tags || []).join(" ")].join("\n");
  const ntext = norm(text);
  let kakaoLeft = 20;
  const kakao = async (q, near) => (kakaoLeft-- > 0 && env.KAKAO_REST_KEY ? kakaoSearch(env, q, near) : []);

  // 1) 영상에 나온 도시 후보: '전주시'처럼 전체 이름은 3점, '전주'처럼 줄인 이름은 1점
  const index = await (await fetch(`${DATA}/cities.json`, { cf: { cacheTtl: 3600 } })).json();
  const all = index.cities;
  const cand = all.map((c) => {
    const b = cityBase(c.name);
    const score = text.includes(c.name) && c.name !== b ? 3 : (b.length >= 2 && text.includes(b) ? 1 : 0);
    return { c, score };
  }).filter((x) => x.score).sort((a, b) => b.score - a.score || b.c.name.length - a.c.name.length).slice(0, 6);

  // 2) 후보 도시의 관광지 중 영상에 나온 곳 (관광공사 공개 데이터라 좌표 포함)
  const found = [];
  for (const x of cand) {
    x.hits = [];
    if (!x.c.hasData) continue;
    const d = await (await fetch(`${DATA}/cities/${x.c.id}.json`, { cf: { cacheTtl: 3600 } })).json();
    for (const s of d.spots) {
      const k = norm(s.name), kb = norm(s.name.split(/\s+/).slice(-1)[0]);
      if ((k.length >= 3 && ntext.includes(k)) || (kb.length >= 3 && !GENERIC.has(kb) && ntext.includes(kb))) x.hits.push(s);
    }
  }
  // '음성'·'진도'처럼 흔한 낱말과 겹치는 도시는 관광지가 실제로 맞을 때만 인정
  let cities = cand.filter((x) => x.hits.length || x.score >= 3)
    .sort((a, b) => (b.hits.length + b.score) - (a.hits.length + a.score)).slice(0, 3);
  if (!cities.length && cand.length) cities = [cand[0]];
  const anchor = cities[0]?.c;
  const near = (c) => (c?.center ? { lat: c.center[0], lng: c.center[1] } : null);

  for (const x of cities) {
    for (const s of x.hits) {
      const base = { name: s.name, cityId: x.c.id, city: x.c.name, spotId: s.id, source: s.kakao && s.lat == null ? "kakao" : "tour" };
      if (s.lat != null) { found.push({ ...base, lat: s.lat, lng: s.lng, kakao: s.kakao || null }); continue; }
      // 카카오에서만 찾은 장소: 위치는 지금 실시간으로 확인
      const docs = await kakao(`${cityBase(x.c.name)} ${s.name}`, near(x.c));
      const doc = docs.find((dd) => dd.id === String(s.kakao)) || docs.find((dd) => norm(dd.place_name) === norm(s.name));
      found.push({ ...base, kakao: s.kakao || doc?.id || null, lat: doc ? +doc.y : null, lng: doc ? +doc.x : null });
    }
  }
  // 3) 설명란 타임라인·핀 이름은 카카오에서 실시간 확인 (좌표는 응답으로만 전달, 저장 안 함)
  const known = found.map((p) => norm(p.name));
  for (const name of extractNames(text)) {
    const n = norm(name);
    if (n.length < 2 || known.some((k) => k.includes(n) || n.includes(k))) continue;
    const docs = await kakao(anchor ? `${cityBase(anchor.name)} ${name}` : name, near(anchor));
    const doc = docs.find((dd) => norm(dd.place_name).includes(n) || n.includes(norm(dd.place_name)));
    if (!doc) continue;
    const c = cityOfAddress(all, doc.address_name) || anchor;
    found.push({ name: doc.place_name, lat: +doc.y, lng: +doc.x, kakao: doc.id, cat: doc.category_group_name || "",
                 cityId: c?.id || null, city: c?.name || "", source: "kakao" });
    known.push(norm(doc.place_name));
  }
  const th = sn.thumbnails || {};
  return {
    video: { id, title: sn.title, channel: sn.channelTitle, views: +(v.statistics?.viewCount || 0),
             thumb: (th.high || th.medium || th.default || {}).url || "" },
    cities: cities.map((x) => ({ id: x.c.id, name: x.c.name })),
    places: found.slice(0, 25),
  };
}

async function handleReport(env, body) {
  const clean = (s, n) => String(s || "").replace(/[<>]/g, "").trim().slice(0, n);
  if (body.website) return { ok: true };   // 스팸 봇용 숨은 칸
  const name = clean(body.name, 60), city = clean(body.city, 30), note = clean(body.note, 400), link = clean(body.link, 300);
  if (name.length < 2 || city.length < 2) return { error: "장소 이름과 도시를 적어 주세요." };
  if (!env.TELEGRAM_TOKEN || !env.TELEGRAM_CHAT_ID) return { error: "제보 받는 곳이 아직 설정되지 않았어요." };
  const text = `📮 어디갈래 숨은 핫플 제보\n장소: ${name}\n도시: ${city}${note ? `\n이유: ${note}` : ""}${link ? `\n링크: ${link}` : ""}`;
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/sendMessage`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT_ID, text, disable_web_page_preview: true }),
  });
  return r.ok ? { ok: true } : { error: "제보를 보내지 못했어요. 잠시 뒤 다시 해 주세요." };
}

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get("Origin") || "";
    if (request.method === "OPTIONS") return new Response(null, { headers: cors(origin) });
    const url = new URL(request.url);
    try {
      if (url.pathname === "/video" && request.method === "GET") {
        const id = videoId(url.searchParams.get("url") || "");
        const cacheKey = new Request(`https://cache.eodigallae/video/${id}`);
        const hit = id && await caches.default.match(cacheKey);
        if (hit) return json(await hit.json(), 200, origin);
        const res = await handleVideo(env, id || "");
        if (!res.error) ctx.waitUntil(caches.default.put(cacheKey, new Response(JSON.stringify(res), { headers: { "Cache-Control": "max-age=3600" } })));
        return json(res, res.error ? 400 : 200, origin);
      }
      if (url.pathname === "/report" && request.method === "POST") {
        const res = await handleReport(env, await request.json().catch(() => ({})));
        return json(res, res.error ? 400 : 200, origin);
      }
      if (url.pathname === "/") return json({ ok: true, service: "어디갈래 도우미" }, 200, origin);
      return json({ error: "없는 주소예요." }, 404, origin);
    } catch (e) {
      return json({ error: "잠시 문제가 생겼어요. 다시 해 주세요." }, 500, origin);
    }
  },
};
