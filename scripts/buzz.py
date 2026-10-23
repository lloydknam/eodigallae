"""요즘 뜨는 곳(화제성) 계산: 유튜브 최근 영상 + 카카오 장소 검색.

원칙
- 유튜브: 도시별로 최근 6개월 '핫플·가볼만한곳·브이로그' 영상을 모아(검색 3회), 각 장소 이름이
  제목·설명·태그에 얼마나 나오는지와 그 영상들의 조회수로 화제성 점수를 낸다. AI는 쓰지 않는다.
- 카카오: 관광공사에 없는 카페·전시·골목 같은 후보를 찾는 데만 쓴다. 카카오 정책상 좌표·주소는
  저장하거나 공개 파일로 내보낼 수 없으므로, 장소 ID(카카오맵 링크)와 이름·분류만 남긴다.
  좌표는 실행 중 같은 장소인지 맞춰 보는 데만 잠깐 쓰고 버린다.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from collections import Counter

YT_SEARCH = "https://www.googleapis.com/youtube/v3/search"
YT_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"
KAKAO_KEYWORD = "https://dapi.kakao.com/v2/local/search/keyword.json"

YT_QUERIES = ["{c} 핫플", "{c} 가볼만한곳", "{c} 여행 브이로그"]
KAKAO_QUERIES = ["{c} 핫플", "{c} 카페거리", "{c} 가볼만한곳", "{c} 전시"]
KAKAO_CATS = {"CE7": "카페", "AT4": "관광명소", "CT1": "문화시설"}

# 영상 설명에 자주 나오지만 장소가 아닌 말
NOT_PLACE = re.compile(r"^(인트로|intro|오프닝|아웃트로|outro|엔딩|ending|마무리|숙소|구독|좋아요|bgm|music|음악|"
                       r"광고|협찬|유료광고|문의|출처|인스타|instagram|타임라인|목차|\d+일차|day\s?\d+|도착|출발|이동)", re.I)
GENERIC = {"카페", "맛집", "시장", "공원", "해변", "바다", "산책", "야경", "숙소", "호텔", "한옥", "거리", "골목",
           "카페거리", "한옥마을", "전망대", "박물관", "미술관", "핫플", "여행", "브이로그"}


def norm(s: str) -> str:
    s = re.sub(r"\(.*?\)|\[.*?\]", "", s or "")
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s).lower()


def city_base(name: str) -> str:
    return re.sub(r"(특별자치시|특별자치도|광역시|특별시|시|군)$", "", name) or name


def name_keys(name: str, city: dict, min_len: int = 3) -> list[str]:
    """장소 이름을 영상 글에서 찾을 때 쓸 열쇠들. '전북 전주 한옥마을' → ['전북전주한옥마을', '전주한옥마을']"""
    base = city_base(city["name"])
    prov = re.sub(r"(특별자치도|특별자치시|광역시|특별시|도)$", "", city.get("province", ""))
    n = norm(name)
    pres = {norm(city["name"]), norm(base), norm(prov), norm(city.get("province", "")), "전북", "전남", "경북",
            "경남", "충북", "충남", "강원", "경기", "제주"} - {""}
    tokens = re.sub(r"\(.*?\)|\[.*?\]", " ", name or "").split()
    keys = {n}
    while len(tokens) > 1 and norm(tokens[0]) in pres:   # 띄어 쓴 지역 이름만 뗀다: '전북 전주 한옥마을' → '한옥마을'
        tokens = tokens[1:]
        keys.add(norm("".join(tokens)))
    out = []
    for k in keys:
        if len(k) < min_len:
            continue
        # '한옥마을'처럼 일반명이어도 '전주 한옥마을'에서 도시 이름을 떼어 낸 것이면(4글자 이상) 그 도시의 그곳으로 본다
        if k in GENERIC and not (k != n and len(k) >= 4):
            continue
        out.append(k)
    return sorted(set(out), key=len, reverse=True)


# ───────────────────────── 유튜브 ─────────────────────────

class YouTube:
    def __init__(self, session, key: str, unit_budget: int):
        self.s, self.key, self.units = session, key, unit_budget

    def _get(self, url, cost, **params):
        if self.units < cost:
            raise RuntimeError("유튜브 하루 할당량(예산) 소진")
        self.units -= cost
        r = self.s.get(url, timeout=20, params={"key": self.key, **params})
        if r.status_code == 403:
            self.units = 0
            raise RuntimeError("유튜브 할당량 초과 또는 키 오류: " + r.text[:150])
        r.raise_for_status()
        return r.json()

    def city_pool(self, city: dict, months: int = 6) -> list[dict]:
        """도시 관련 최근 영상 모음 (검색 3회 = 300 unit + 상세 조회 몇 unit)."""
        base = city_base(city["name"])
        after = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * months)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ids: list[str] = []
        for q in YT_QUERIES:
            js = self._get(YT_SEARCH, 100, part="id", q=q.format(c=base), type="video", maxResults=50,
                           regionCode="KR", relevanceLanguage="ko", publishedAfter=after, safeSearch="moderate")
            for it in js.get("items", []):
                vid = it.get("id", {}).get("videoId")
                if vid and vid not in ids:
                    ids.append(vid)
        pool = []
        for i in range(0, len(ids), 50):
            js = self._get(YT_VIDEOS, 1, part="snippet,statistics", id=",".join(ids[i:i + 50]), maxResults=50)
            for v in js.get("items", []):
                sn, st = v.get("snippet", {}), v.get("statistics", {})
                text = " ".join([sn.get("title", ""), sn.get("description", "")[:3000], " ".join(sn.get("tags", [])[:30])])
                if base not in text and norm(city["name"]) not in norm(text):
                    continue   # 다른 지역 영상 제외
                th = sn.get("thumbnails", {})
                pool.append({
                    "id": v["id"],
                    "title": sn.get("title", "")[:120],
                    "channel": sn.get("channelTitle", "")[:40],
                    "published": sn.get("publishedAt", "")[:10],
                    "views": int(st.get("viewCount", 0) or 0),
                    "thumb": (th.get("high") or th.get("medium") or th.get("default") or {}).get("url", ""),
                    "text": text[:3500],
                })
        return pool


def video_weight(v: dict, today: dt.date) -> float:
    try:
        age = (today - dt.date.fromisoformat(v["published"])).days
    except ValueError:
        age = 365
    rec = 1.0 if age <= 90 else 0.7 if age <= 180 else 0.4
    return math.log10(v["views"] + 10) * rec


def score_places(places: list[dict], pool: list[dict], city: dict) -> None:
    """각 장소에 yt 점수·관련 영상을 붙인다. 제목에 나오면 2배."""
    today = dt.date.today()
    prepared = [(v, norm(v["title"]), norm(v["text"])) for v in pool]
    for p in places:
        keys = name_keys(p["name"], city, 2 if p.get("curated") else 3)
        if not keys:
            continue
        # 3글자 이하 짧은 이름은 '경기 전주'→'경기전'처럼 우연히 붙는 경우가 있어, 원문에서 단어 경계로 찾는다
        short = [re.compile(r"(?<![가-힣A-Za-z0-9])" + re.escape(k) + r"(?![가-힣A-Za-z0-9]|[가-힣]{2,})|(?<![가-힣A-Za-z0-9])"
                            + re.escape(k) + r"(?=(?:에서|에게|으로|에는|까지|부터|이랑|[에은는이가을를의도와과로서])(?:[^가-힣]|$))")
                 for k in keys if len(k) <= 3]
        long_ = [k for k in keys if len(k) > 3]

        def found(n_text, raw):
            return any(k in n_text for k in long_) or any(r.search(raw) for r in short)
        hits = []
        for v, nt, nx in prepared:
            in_title = found(nt, v["title"])
            if in_title or found(nx, v["text"]):
                hits.append((video_weight(v, today) * (2 if in_title else 1), v))
        if hits:
            channels = {v["channel"] for _, v in hits}
            p["yt"] = {"n": len(hits), "views": sum(v["views"] for _, v in hits),
                       "score": round(sum(w for w, _ in hits) * (1 + 0.15 * (len(channels) - 1)), 2)}
            top = sorted((v for _, v in hits), key=lambda v: -v["views"])[:4]
            p["videos"] = [{k: v[k] for k in ("id", "title", "channel", "thumb", "published", "views")} for v in top]


# ───────────────────────── 영상 속 장소 이름 뽑기 ─────────────────────────

TS_LINE = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}\s*[-–—|~:]?\s*(.+)$")
PIN_LINE = re.compile(r"^\s*(?:📍|🏠|☕|🍽|📌|▶|✔|①|②|③|④|⑤|\d+\.)\s*(.+)$")


def extract_names(pool: list[dict], city: dict) -> list[tuple[str, int, int]]:
    """영상 설명의 타임라인(00:35 장소)·핀(📍장소) 줄에서 장소 이름 후보를 뽑아, 여러 영상에 나온 순으로."""
    base = city_base(city["name"])
    seen_in: dict[str, set] = {}
    views: Counter = Counter()
    label: dict[str, str] = {}
    for v in pool:
        for line in v["text"].splitlines():
            m = TS_LINE.match(line) or PIN_LINE.match(line)
            if not m:
                continue
            t = re.split(r"\s[-–—|/]\s|[:：(]|https?://", m.group(1))[0]
            t = re.sub(r"[^\w\s가-힣&'·.]", " ", t).strip()
            t = re.sub(r"^(?:%s|%s시|%s군)\s+" % (base, base, base), "", t)
            if not (2 <= len(t) <= 20) or NOT_PLACE.match(t) or norm(t) in GENERIC or len(norm(t)) < 2:
                continue
            k = norm(t)
            seen_in.setdefault(k, set()).add(v["id"])
            views[k] += v["views"]
            label.setdefault(k, t)
    ranked = sorted(seen_in, key=lambda k: (-len(seen_in[k]), -views[k]))
    return [(label[k], len(seen_in[k]), views[k]) for k in ranked
            if len(seen_in[k]) >= 2 or views[k] >= 30000][:40]


# ───────────────────────── 카카오 ─────────────────────────

class Kakao:
    def __init__(self, session, key: str, max_calls: int = 300):
        self.s, self.key, self.left = session, key, max_calls

    def search(self, query: str, x: float | None, y: float | None, page: int = 1) -> list[dict]:
        if self.left <= 0:
            return []
        self.left -= 1
        params = {"query": query, "size": 15, "page": page, "sort": "accuracy"}
        if x and y:
            params.update({"x": x, "y": y, "radius": 20000})
        r = self.s.get(KAKAO_KEYWORD, timeout=15, params=params, headers={"Authorization": f"KakaoAK {self.key}"})
        if r.status_code in (401, 403):
            self.left = 0
            raise RuntimeError("카카오 키 오류 또는 권한 없음: " + r.text[:150])
        r.raise_for_status()
        return r.json().get("documents", [])


def in_city(doc: dict, city: dict) -> bool:
    addr = (doc.get("address_name") or "") + " " + (doc.get("road_address_name") or "")
    base = city_base(city["name"])
    return city["name"] in addr or (base in addr and len(base) >= 2)


def discover_kakao(kakao: Kakao, city: dict, center: tuple[float, float] | None, names: list[str]) -> list[dict]:
    """카카오에서 후보 장소 찾기. 반환: [{kakao, name, cat, _lat, _lng}] (_로 시작하는 값은 저장하지 않음)"""
    base = city_base(city["name"])
    x, y = (center[1], center[0]) if center else (None, None)
    found: dict[str, dict] = {}

    def take(doc, hint=None):
        code = doc.get("category_group_code", "")
        if code not in KAKAO_CATS or not in_city(doc, city):
            return
        if hint and not (norm(hint) in norm(doc["place_name"]) or norm(doc["place_name"]) in norm(hint)):
            return
        found.setdefault(doc["id"], {"kakao": doc["id"], "name": doc["place_name"], "cat": KAKAO_CATS[code],
                                     "_lat": float(doc["y"]), "_lng": float(doc["x"])})

    for q in KAKAO_QUERIES:
        for page in (1, 2):
            docs = kakao.search(q.format(c=base), x, y, page)
            for d in docs:
                take(d)
            if len(docs) < 15:
                break
    for n in names[:25]:
        docs = kakao.search(f"{base} {n}", x, y)
        for d in docs[:3]:
            take(d, hint=n)
    return list(found.values())
