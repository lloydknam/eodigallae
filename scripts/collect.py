#!/usr/bin/env python3
"""
여행 플래너 데이터 수집기

전국 시·군 목록, 관광지·문화시설·음식점(한국관광공사 TourAPI),
관광지별 최신 영상(YouTube Data API), 도시별 추천 코스(Claude API, 선택)를
모아서 data/ 아래 JSON으로 저장한다. 웹앱은 이 JSON만 읽는다.

환경변수
  TOURAPI_KEY        공공데이터포털 '한국관광공사_국문 관광정보 서비스' 일반 인증키(Decoding)  [필수]
  YOUTUBE_API_KEY    YouTube Data API v3 키                                              [선택]
  ANTHROPIC_API_KEY  Claude API 키 (추천 코스 생성)                                       [선택]
  CLAUDE_MODEL       기본 claude-haiku-5-5

사용 예
  python scripts/collect.py --batch 60          # 갱신이 가장 오래된 도시 60곳 처리
  python scripts/collect.py --cities 전주시,남원시,원주시
  python scripts/collect.py --only-city-list    # 도시 목록만 갱신
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CITY_DIR = DATA / "cities"
CACHE_DIR = DATA / "cache"

TOUR_BASE = "https://apis.data.go.kr/B551011/KorService2"
HUB_BASE = "https://apis.data.go.kr/B551011/LocgoHubTarService1"  # 지자체 중심 관광지(T map 내비 검색 기반 인기 순위)
YT_SEARCH = "https://www.googleapis.com/youtube/v3/search"
CLAUDE_URL = "https://api.anthropic.com/v1/messages"

# TourAPI 지역코드 1~8은 특별·광역시/세종 → 시 전체를 하나의 '도시'로 다룬다.
METRO_AREA_CODES = {"1", "2", "3", "4", "5", "6", "7", "8"}

CT_SPOT, CT_CULTURE, CT_FOOD = "12", "14", "39"

KST = dt.timezone(dt.timedelta(hours=9))
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "korea-trip-collector/1.0"


def now_iso() -> str:
    return dt.datetime.now(KST).isoformat(timespec="seconds")


def log(*a):
    print(*a, flush=True)


# ───────────────────────── 공통 유틸 ─────────────────────────

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, obj, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":") if compact else None,
                     indent=None if compact else 1)
    path.write_text(txt, encoding="utf-8")


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def clean_text(s: str | None, limit: int | None = None) -> str:
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s


# ───────────────────────── TourAPI ─────────────────────────

class TourAPI:
    def __init__(self, key: str, max_calls: int):
        self.key = key
        self.calls = 0
        self.max_calls = max_calls
        self.hub_off = False

    def get_hub(self, **params) -> list[dict]:
        """지자체 중심 관광지 API. 활용신청 전이면 빈 목록(순위 없이 진행)."""
        if self.hub_off:
            return []
        try:
            return self.get("areaBasedList1", _base=HUB_BASE, **params)
        except RuntimeError as e:
            log("   인기 순위 API 사용 불가(활용신청 확인), 순위 없이 진행:", str(e)[:120])
            self.hub_off = True
            return []

    def get(self, endpoint: str, _base: str = TOUR_BASE, **params) -> list[dict]:
        if self.calls >= self.max_calls:
            raise RuntimeError(f"TourAPI 호출 한도({self.max_calls}) 도달")
        q = {"serviceKey": self.key, "MobileOS": "ETC", "MobileApp": "KoreaTrip", "_type": "json"}
        q.update({k: v for k, v in params.items() if v is not None})
        last_err = None
        for attempt in range(3):
            self.calls += 1
            try:
                r = SESSION.get(f"{_base}/{endpoint}", params=q, timeout=20)
                text = r.text.strip()
                if not text.startswith("{"):
                    # 인증키 오류 등은 XML로 온다
                    msg = re.search(r"<returnAuthMsg>(.*?)</returnAuthMsg>|<resultMsg>(.*?)</resultMsg>", text)
                    raise RuntimeError(f"TourAPI 비정상 응답: {msg.group(0) if msg else text[:200]}")
                js = r.json()
                if "response" not in js:
                    raise RuntimeError(f"TourAPI 오류: {js.get('resultCode')} {js.get('resultMsg')}")
                head = js["response"]["header"]
                if head.get("resultCode") != "0000":
                    raise RuntimeError(f"TourAPI 오류: {head.get('resultCode')} {head.get('resultMsg')}")
                body = js["response"].get("body") or {}
                items = body.get("items") or {}
                if not isinstance(items, dict):  # 결과 없음이면 "" 로 온다
                    return []
                item = items.get("item") or []
                return item if isinstance(item, list) else [item]
            except (requests.RequestException, ValueError, RuntimeError) as e:
                last_err = e
                if "인증" in str(e) or "SERVICE_KEY" in str(e):
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"{endpoint} 실패: {last_err}")

    def list_all(self, endpoint: str, max_rows: int, **params) -> list[dict]:
        rows, page = [], 1
        while len(rows) < max_rows:
            n = min(100, max_rows - len(rows))
            batch = self.get(endpoint, numOfRows=n, pageNo=page, **params)
            rows.extend(batch)
            if len(batch) < n:
                break
            page += 1
        return rows


def build_city_list(api: TourAPI) -> list[dict]:
    """TourAPI 지역코드로 전국 '도시' 목록 생성: 특별·광역시는 시 단위, 도는 시·군 단위."""
    cities = []
    for area in api.get("areaCode2", numOfRows=50):
        acode, aname = str(area["code"]), area["name"]
        if acode in METRO_AREA_CODES:
            cities.append({"id": f"a{acode}", "name": aname, "province": aname,
                           "areaCode": acode, "sigunguCode": None})
            continue
        for sg in api.get("areaCode2", areaCode=acode, numOfRows=100):
            cities.append({"id": f"a{acode}-s{sg['code']}", "name": sg["name"], "province": aname,
                           "areaCode": acode, "sigunguCode": str(sg["code"])})
    return cities


def to_place(it: dict) -> dict | None:
    try:
        lat, lng = float(it.get("mapy") or 0), float(it.get("mapx") or 0)
    except ValueError:
        return None
    if not (33 < lat < 39 and 124 < lng < 132):
        return None
    return {
        "id": str(it["contentid"]),
        "type": str(it.get("contenttypeid", "")),
        "name": clean_text(it.get("title")),
        "addr": clean_text(f"{it.get('addr1') or ''} {it.get('addr2') or ''}"),
        "lat": round(lat, 6),
        "lng": round(lng, 6),
        "image": (it.get("firstimage") or "").replace("http://", "https://"),
        "thumb": (it.get("firstimage2") or it.get("firstimage") or "").replace("http://", "https://"),
        "tel": clean_text(it.get("tel")),
        "modified": it.get("modifiedtime", ""),
        "ld": (str(it.get("lDongRegnCd") or ""), str(it.get("lDongSignguCd") or "")),
    }


def fetch_places(api: TourAPI, city: dict, ctype: str, max_rows: int) -> list[dict]:
    """도시의 해당 유형 항목을 최대 max_rows개까지 전부 가져온다.
    유명 관광지가 빠지지 않도록 '일부'가 아니라 '전체'를 받아 인기 순위로 다시 줄 세운다."""
    items = api.list_all("areaBasedList2", max_rows, areaCode=city["areaCode"],
                         sigunguCode=city["sigunguCode"], contentTypeId=ctype, arrange="C")
    seen, out = set(), []
    for it in items:
        p = to_place(it)
        if p and p["id"] not in seen:
            seen.add(p["id"])
            out.append(p)
    return out


# ───────────────────────── 인기 순위 (지자체 중심 관광지) ─────────────────────────

def norm_name(s: str) -> str:
    s = re.sub(r"\(.*?\)|\[.*?\]", "", s or "")
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s).lower()


def fetch_hub(api: TourAPI, codes: set[str]) -> list[dict]:
    """법정 시군구 코드(5자리)별 인기 상위 100곳. 공급 지연을 감안해 2~4개월 전 자료부터 시도."""
    today = dt.date.today().replace(day=1)
    out: dict[str, dict] = {}
    for code in sorted(codes):
        for back in (2, 3, 4):
            y, m = today.year, today.month - back
            while m <= 0:
                y, m = y - 1, m + 12
            rows = api.get_hub(baseYm=f"{y}{m:02d}", areaCd=code[:2], signguCd=code, numOfRows=100, pageNo=1)
            if rows:
                break
        for r in rows:
            try:
                lat, lng = float(r.get("mapY") or 0), float(r.get("mapX") or 0)
                rank = int(r.get("hubRank") or 999)
            except ValueError:
                continue
            key = str(r.get("hubTatsCd") or r.get("hubTatsNm"))
            item = {"code": key, "name": clean_text(r.get("hubTatsNm")), "rank": rank, "lat": lat, "lng": lng,
                    "cat": f"{r.get('hubCtgryLclsNm') or ''}/{r.get('hubCtgryMclsNm') or ''}"}
            if key not in out or rank < out[key]["rank"]:
                out[key] = item
    return sorted(out.values(), key=lambda x: x["rank"])


def match_hub(places: list[dict], hub: list[dict]) -> None:
    """TourAPI 장소에 인기 순위(rank)를 붙인다: 이름이 같거나 한쪽이 다른 쪽을 포함하고 가까우면 같은 곳."""
    index = [(norm_name(h["name"]), h) for h in hub]
    for p in places:
        n = norm_name(p["name"])
        best = None
        for hn, h in index:
            if not hn or not n:
                continue
            same = hn == n
            part = len(min(hn, n, key=len)) >= 3 and (hn in n or n in hn)
            if not (same or part):
                continue
            d = haversine_km(p["lat"], p["lng"], h["lat"], h["lng"]) if h["lat"] else 0
            if d <= (3.0 if same else 1.5) and (best is None or h["rank"] < best["rank"]):
                best = h
        if best:
            p["rank"] = best["rank"]
            best["matched"] = True


# ───────────────────────── YouTube ─────────────────────────

def youtube_search(key: str, query: str, months: int = 24) -> list[dict]:
    after = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * months)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = SESSION.get(YT_SEARCH, timeout=20, params={
        "key": key, "part": "snippet", "q": query, "type": "video", "maxResults": 4,
        "regionCode": "KR", "relevanceLanguage": "ko", "order": "relevance",
        "publishedAfter": after, "safeSearch": "strict", "videoEmbeddable": "true",
    })
    if r.status_code == 403:
        raise RuntimeError("YouTube 할당량 초과 또는 키 오류")
    r.raise_for_status()
    out = []
    for it in r.json().get("items", []):
        sn = it["snippet"]
        thumbs = sn.get("thumbnails", {})
        th = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
        out.append({
            "id": it["id"]["videoId"],
            "title": clean_text(sn.get("title")),
            "channel": clean_text(sn.get("channelTitle")),
            "thumb": th,
            "published": sn.get("publishedAt", "")[:10],
        })
    return out


# ───────────────────────── 코스 생성 ─────────────────────────

def nearest_neighbor_order(points: list[dict]) -> list[dict]:
    if not points:
        return []
    rest = points[1:]
    route = [points[0]]
    while rest:
        cur = route[-1]
        nxt = min(rest, key=lambda p: haversine_km(cur["lat"], cur["lng"], p["lat"], p["lng"]))
        rest.remove(nxt)
        route.append(nxt)
    return route


def food_rank_key(p: dict, f: dict):
    return (f.get("rank", 999), haversine_km(p["lat"], p["lng"], f["lat"], f["lng"]))


def heuristic_courses(spots: list[dict], foods: list[dict]) -> list[dict]:
    """Claude 키가 없을 때: 인기 순위가 높은 관광지를 중심으로 가까운 곳끼리 하루씩 묶는다."""
    pool = spots[:12]
    if len(pool) < 2:
        return []

    def build_day(pool):
        anchor = pool[0]  # 남은 곳 중 가장 인기 있는 곳
        near = sorted(pool[1:], key=lambda p: haversine_km(anchor["lat"], anchor["lng"], p["lat"], p["lng"]))
        group = [anchor] + [p for p in near if haversine_km(anchor["lat"], anchor["lng"], p["lat"], p["lng"]) <= 15][:3]
        start = max(group, key=lambda p: haversine_km(anchor["lat"], anchor["lng"], p["lat"], p["lng"]))
        rest = [p for p in group if p is not start]
        return nearest_neighbor_order([start] + rest)

    def meal_near(p, used):
        cands = [f for f in foods if f["id"] not in used and haversine_km(p["lat"], p["lng"], f["lat"], f["lng"]) <= 2.5]
        return min(cands, key=lambda f: food_rank_key(p, f)) if cands else None

    def make_day(label, seq, used):
        stops = []
        for i, s in enumerate(seq):
            stops.append({"kind": "spot", "id": s["id"]})
            if i == 1 and (m := meal_near(s, used)):
                used.add(m["id"])
                stops.append({"kind": "meal", "id": m["id"], "note": "점심"})
        if seq and (m := meal_near(seq[-1], used)):
            used.add(m["id"])
            stops.append({"kind": "meal", "id": m["id"], "note": "저녁"})
        return {"label": label, "stops": stops}

    day1 = build_day(pool)
    courses = [{"title": "하루 핵심 코스", "summary": "가장 많이 찾는 곳을 중심으로 가까운 곳끼리 묶었어요.",
                "days": [make_day("1일차", day1, set())]}]
    rest = [p for p in pool if p not in day1]
    if len(rest) >= 2:
        day2 = build_day(rest)
        courses.append({"title": "1박 2일 코스", "summary": "둘째 날은 다음으로 인기 있는 지역을 돌아봐요.",
                        "days": [make_day("1일차", day1, used := set()), make_day("2일차", day2, used)]})
    return courses


COURSE_PROMPT = """너는 한국 국내여행 코스 기획자야. 아래는 {city}({province})의 관광지·식당 목록이야(JSON).
여행자가 대중교통이나 자가용으로 무리 없이 다닐 수 있는 추천 코스를 만들어줘.

규칙
- 반드시 목록에 있는 id만 사용. 목록에 없는 장소는 절대 만들지 말 것.
- 코스 2~3개: "하루 핵심 코스"(1일), "1박 2일 코스"(2일) 필수, 필요하면 테마 코스 1개(예: 자연, 역사, 아이와 함께).
- 하루 관광지 3~5곳, 동선은 지리적으로 가깝게 이어지도록 좌표를 고려.
- 점심·저녁 식당은 직전 관광지 근처의 식당 id로 넣고, 식당 목록이 비어 있으면 생략.
- note는 20자 이내 한국어 팁.
- summary는 40자 이내.

출력은 JSON만, 다른 말 없이:
{{"courses":[{{"title":"...","summary":"...","days":[{{"label":"1일차","stops":[{{"kind":"spot","id":"...","note":"..."}},{{"kind":"meal","id":"...","note":"점심"}}]}}]}}]}}

관광지: {spots}
식당: {foods}
"""


def claude_courses(key: str, model: str, city: dict, spots: list[dict], foods: list[dict]) -> list[dict] | None:
    sp = [{"id": s["id"], "name": s["name"], "lat": round(s["lat"], 4), "lng": round(s["lng"], 4),
           "desc": s.get("desc", "")[:80]} for s in spots[:25]]
    fd = [{"id": f["id"], "name": f["name"], "lat": round(f["lat"], 4), "lng": round(f["lng"], 4)}
          for f in foods[:40]]
    prompt = COURSE_PROMPT.format(city=city["name"], province=city["province"],
                                  spots=json.dumps(sp, ensure_ascii=False),
                                  foods=json.dumps(fd, ensure_ascii=False))
    r = SESSION.post(CLAUDE_URL, timeout=90, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json",
    }, json={"model": model, "max_tokens": 2500, "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    data = json.loads(m.group(0))
    spot_ids = {s["id"] for s in spots}
    food_ids = {f["id"] for f in foods}
    courses = []
    for c in data.get("courses", []):
        days = []
        for d in c.get("days", []):
            stops = [s for s in d.get("stops", [])
                     if (s.get("kind") == "spot" and str(s.get("id")) in spot_ids)
                     or (s.get("kind") == "meal" and str(s.get("id")) in food_ids)]
            for s in stops:
                s["id"] = str(s["id"])
                s["note"] = clean_text(s.get("note"), 30)
            if sum(1 for s in stops if s["kind"] == "spot") >= 2:
                days.append({"label": clean_text(d.get("label"), 10) or f"{len(days)+1}일차", "stops": stops})
        if days:
            courses.append({"title": clean_text(c.get("title"), 20), "summary": clean_text(c.get("summary"), 60),
                            "days": days})
    return courses or None


# ───────────────────────── 도시 처리 ─────────────────────────

def process_city(city: dict, api: TourAPI, args, caches: dict, budget: dict) -> dict:
    log(f"▶ {city['province']} {city['name']}")
    spots = fetch_places(api, city, CT_SPOT, args.fetch_rows)
    culture = fetch_places(api, city, CT_CULTURE, 100)
    foods = fetch_places(api, city, CT_FOOD, args.fetch_rows)
    allp = spots + culture

    # 인기 순위: TourAPI 항목의 법정 시군구 코드로 '지자체 중심 관광지'를 조회 (30일 캐시)
    hc = caches["hub"]
    hentry = hc.get(city["id"])
    if hentry and hentry.get("at", "") >= (dt.date.today() - dt.timedelta(days=30)).isoformat():
        hub = hentry["items"]
    else:
        codes = {a + b if len(b) <= 3 and len(a) == 2 else b for a, b in (p["ld"] for p in allp + foods) if a and b}
        codes = {c for c in codes if re.fullmatch(r"\d{5}", c)}
        hub = fetch_hub(api, codes) if codes else []
        if hub:
            hc[city["id"]] = {"at": dt.date.today().isoformat(), "items": hub}
    hub_food = [h for h in hub if "음식" in h["cat"]]
    hub_spot = [h for h in hub if "음식" not in h["cat"] and not re.search(r"숙박|쇼핑", h["cat"])]
    match_hub(allp, hub_spot)
    match_hub(foods, hub_food)
    # 인기 맛집 중 관광공사 목록에 없는 곳도 이름·좌표로 추가 (상세는 카카오맵 링크)
    for h in hub_food:
        if not h.get("matched") and h["lat"]:
            foods.append({"id": f"h{h['code']}", "type": "hub", "name": h["name"], "addr": "", "lat": h["lat"],
                          "lng": h["lng"], "image": "", "thumb": "", "tel": "", "rank": h["rank"]})
    log(f"   인기 순위 {len(hub)}곳 · 관광지 매칭 {sum(1 for p in allp if 'rank' in p)}")

    # 순위 있는 곳(인기순) → 순위 없는 곳 중 사진 있는 관광지 → 나머지
    allp.sort(key=lambda p: (p.get("rank", 999), not p["image"], p["type"] != CT_SPOT))
    places = allp[: args.max_spots]
    for p in places:
        p.setdefault("desc", "")
        p.setdefault("videos", [])

    # 개요(설명): 캐시 우선, 없으면 상위 일부만 detailCommon2 호출
    ov = caches["overview"]
    for p in places[: args.overview_top]:
        if p["id"] not in ov and budget["overview"] > 0:
            try:
                d = api.get("detailCommon2", contentId=p["id"])
                ov[p["id"]] = clean_text((d[0] if d else {}).get("overview"), 160)
            except RuntimeError as e:
                log("   개요 실패:", e)
                ov[p["id"]] = ""
            budget["overview"] -= 1
        p["desc"] = ov.get(p["id"], "")

    # 관광지별 주변 식당: 2km 이내에서 인기 순위 → 거리 순으로 3곳
    for p in places:
        near = [f for f in foods if haversine_km(p["lat"], p["lng"], f["lat"], f["lng"]) <= 2.0]
        p["foods"] = [f["id"] for f in sorted(near, key=lambda f: food_rank_key(p, f))[:3]]

    # 영상: 캐시가 오래된 순으로 할당량 안에서 갱신
    vc = caches["videos"]
    for p in places[: args.video_top]:
        entry = vc.get(p["id"])
        stale = (not entry) or (entry.get("at", "") < (dt.date.today() - dt.timedelta(days=args.video_days)).isoformat())
        if args.youtube_key and stale and budget["youtube"] > 0:
            base = re.sub(r"(특별자치시|특별자치도|광역시|특별시|시|군)$", "", city["name"]) or city["name"]
            q = f"{base} {p['name']} 여행"
            try:
                vc[p["id"]] = {"at": dt.date.today().isoformat(), "items": youtube_search(args.youtube_key, q)}
            except Exception as e:  # noqa: BLE001
                log("   유튜브 중단:", e)
                budget["youtube"] = 0
            budget["youtube"] -= 1
        p["videos"] = (vc.get(p["id"]) or {}).get("items", [])

    # 코스: 관광지 구성이 바뀌었거나 30일 지나면 재생성
    cc = caches["courses"]
    sig = ",".join(p["id"] for p in places[:25])
    entry = cc.get(city["id"])
    courses = None
    if entry and entry.get("sig") == sig and entry.get("at", "") >= (dt.date.today() - dt.timedelta(days=30)).isoformat():
        courses = entry["courses"]
    elif args.anthropic_key and budget["claude"] > 0:
        try:
            courses = claude_courses(args.anthropic_key, args.model, city, places, foods)
            budget["claude"] -= 1
        except Exception as e:  # noqa: BLE001
            log("   코스 생성 실패, 기본 코스로 대체:", e)
        if courses:
            cc[city["id"]] = {"sig": sig, "at": dt.date.today().isoformat(), "courses": courses, "by": "claude"}
    if not courses:
        courses = heuristic_courses(places, foods)
    # 캐시된 코스가 사라진 장소를 가리키지 않도록 정리
    valid = {p["id"] for p in places} | {f["id"] for f in foods}
    for c in courses:
        for d in c["days"]:
            d["stops"] = [s for s in d["stops"] if s["id"] in valid]

    used_food = {fid for p in places for fid in p["foods"]} | {
        s["id"] for c in courses for d in c["days"] for s in d["stops"] if s["kind"] == "meal"}
    food_out = [{**{k: f[k] for k in ("id", "name", "addr", "lat", "lng", "thumb", "tel")},
                 **({"rank": f["rank"]} if "rank" in f else {})}
                for f in sorted(foods, key=lambda f: f.get("rank", 999)) if f["id"] in used_food]

    center = ([round(sum(p["lat"] for p in places) / len(places), 5),
               round(sum(p["lng"] for p in places) / len(places), 5)] if places else None)
    out = {
        "id": city["id"], "name": city["name"], "province": city["province"],
        "center": center, "updatedAt": now_iso(), "sample": False,
        "spots": [{**{k: p[k] for k in ("id", "type", "name", "addr", "lat", "lng", "image", "thumb", "desc", "videos", "foods")},
                   **({"rank": p["rank"]} if "rank" in p else {})}
                  for p in places],
        "restaurants": food_out,
        "courses": courses,
        "credit": "관광정보: 한국관광공사 TourAPI(공공누리) · 인기 순위: 한국관광공사 지자체 중심 관광지(T map 검색 기반) · 영상: YouTube",
    }
    save_json(CITY_DIR / f"{city['id']}.json", out, compact=True)
    log(f"   관광지 {len(out['spots'])} · 식당 {len(food_out)} · 코스 {len(courses)}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=40, help="이번 실행에서 처리할 도시 수(오래된 순)")
    ap.add_argument("--cities", default="", help="쉼표로 구분한 도시 이름 또는 id (지정 시 batch 무시)")
    ap.add_argument("--only-city-list", action="store_true")
    ap.add_argument("--max-spots", type=int, default=30)
    ap.add_argument("--fetch-rows", type=int, default=400, help="유형별로 받아올 최대 항목 수(전체 후보)")
    ap.add_argument("--overview-top", type=int, default=10)
    ap.add_argument("--video-top", type=int, default=6)
    ap.add_argument("--video-days", type=int, default=14, help="영상 캐시 유효기간(일)")
    ap.add_argument("--tour-max-calls", type=int, default=900, help="TourAPI 하루 호출 상한(개발계정 1,000)")
    ap.add_argument("--overview-budget", type=int, default=250)
    ap.add_argument("--youtube-budget", type=int, default=90, help="검색 1회=100 unit, 기본 할당 10,000/일")
    ap.add_argument("--claude-budget", type=int, default=40)
    args = ap.parse_args()

    tour_key = os.environ.get("TOURAPI_KEY", "").strip()
    if not tour_key:
        sys.exit("TOURAPI_KEY 환경변수가 필요합니다 (공공데이터포털 일반 인증키 Decoding).")
    args.youtube_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    args.anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    args.model = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")

    api = TourAPI(tour_key, args.tour_max_calls)
    index_path = DATA / "cities.json"
    index = load_json(index_path, {"updatedAt": None, "cities": []})
    if index.pop("sample", False):  # 샘플 목록이면 실데이터 목록으로 교체
        index["cities"] = []

    # 도시 목록은 7일마다 갱신 (코드 변경 대비)
    meta = load_json(CACHE_DIR / "meta.json", {})
    if args.only_city_list or not index["cities"] or meta.get("cityListAt", "") < (dt.date.today() - dt.timedelta(days=7)).isoformat():
        fresh = build_city_list(api)
        old = {c["id"]: c for c in index["cities"]}
        index["cities"] = [{**old.get(c["id"], {}), **c} for c in fresh]
        meta["cityListAt"] = dt.date.today().isoformat()
        save_json(CACHE_DIR / "meta.json", meta)
        log(f"도시 목록 {len(index['cities'])}곳")
    if args.only_city_list:
        index["updatedAt"] = now_iso()
        save_json(index_path, index)
        return

    if args.cities:
        wanted = {w.strip() for w in args.cities.split(",") if w.strip()}
        targets = [c for c in index["cities"] if c["name"] in wanted or c["id"] in wanted]
    else:
        targets = sorted(index["cities"], key=lambda c: c.get("updatedAt") or "")[: args.batch]

    caches = {name: load_json(CACHE_DIR / f"{name}.json", {}) for name in ("overview", "videos", "courses", "hub")}
    budget = {"overview": args.overview_budget, "youtube": args.youtube_budget, "claude": args.claude_budget}

    for city in targets:
        try:
            out = process_city(city, api, args, caches, budget)
        except RuntimeError as e:
            log("   건너뜀:", e)
            if "한도" in str(e) or "인증" in str(e):
                break
            continue
        city.update({
            "hasData": bool(out["spots"]), "spotCount": len(out["spots"]),
            "image": next((s["thumb"] for s in out["spots"] if s["thumb"]), ""),
            "updatedAt": out["updatedAt"], "center": out["center"],
        })
        # 중간 저장(실행이 끊겨도 진행분 보존)
        for name, obj in caches.items():
            save_json(CACHE_DIR / f"{name}.json", obj, compact=True)
        index["updatedAt"] = now_iso()
        save_json(index_path, index)

    log(f"완료 · TourAPI 호출 {api.calls}회 · 남은 YouTube 예산 {max(budget['youtube'], 0)}")


if __name__ == "__main__":
    main()
