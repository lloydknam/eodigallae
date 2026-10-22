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
import collections
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
# TourAPI 지역코드에 남아 있는 옛 행정구역 (통합·폐지)
ABOLISHED = {"마산시", "진해시", "남제주군", "북제주군", "청원군", "연기군"}

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

class QuotaError(RuntimeError):
    pass


class TourAPI:
    def __init__(self, key: str, max_calls: int):
        self.key = key
        self.calls = 0          # 관광정보 서비스(KorService2) 호출 수
        self.hub_calls = 0      # 지자체 중심 관광지 서비스 호출 수 (공공데이터포털 한도는 서비스별로 따로)
        self.max_calls = max_calls
        self.hub_off = False
        self.hub_ym: str | None = None   # 자료가 있는 기준월을 한 번 찾으면 계속 사용

    def get_hub(self, **params) -> list[dict]:
        """지자체 중심 관광지 API. 활용신청 전이면 빈 목록(순위 없이 진행)."""
        if self.hub_off or self.hub_calls >= self.max_calls:
            return []
        try:
            return self.get("areaBasedList1", _base=HUB_BASE, **params)
        except RuntimeError as e:
            log("   인기 순위 API 사용 불가(활용신청 확인), 순위 없이 진행:", str(e)[:120])
            self.hub_off = True
            return []

    def get(self, endpoint: str, _base: str = TOUR_BASE, **params) -> list[dict]:
        hub = _base == HUB_BASE
        if not hub and self.calls >= self.max_calls:
            raise QuotaError(f"TourAPI 호출 한도({self.max_calls}) 도달")
        q = {"serviceKey": self.key, "MobileOS": "ETC", "MobileApp": "KoreaTrip", "_type": "json"}
        q.update({k: v for k, v in params.items() if v is not None})
        last_err = None
        for attempt in range(3):
            if hub:
                self.hub_calls += 1
            else:
                self.calls += 1
            try:
                r = SESSION.get(f"{_base}/{endpoint}", params=q, timeout=20)
                text = r.text.strip()
                if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in text or r.status_code == 429:
                    raise QuotaError("공공데이터포털 하루 호출 한도 초과 (내일 자동으로 이어서 수집)")
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
            except QuotaError:
                if hub:
                    self.hub_off = True
                    return []
                raise
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
            if sg["name"] in ABOLISHED:
                continue
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
        "name": re.sub(r"\s*\[[^\]]*\]\s*$", "", clean_text(it.get("title"))),  # '[슬로시티]' 같은 꼬리표 제거
        "addr": clean_text(f"{it.get('addr1') or ''} {it.get('addr2') or ''}"),
        "lat": round(lat, 6),
        "lng": round(lng, 6),
        "image": (it.get("firstimage") or "").replace("http://", "https://"),
        "thumb": (it.get("firstimage2") or it.get("firstimage") or "").replace("http://", "https://"),
        "tel": clean_text(it.get("tel")),
        "modified": it.get("modifiedtime", ""),
        "ld": (str(it.get("lDongRegnCd") or ""), str(it.get("lDongSignguCd") or "")),
    }


def fetch_places(api: TourAPI, city: dict, ctype: str, max_rows: int, ldong: set[str] | None = None) -> list[dict]:
    """도시의 해당 유형 항목을 전부 가져온다. 관광공사 4.3 개편 이후 옛 지역코드(areaCode/sigunguCode)가
    비어 있는 항목이 많아, 새 법정동 코드(lDongRegnCd/lDongSignguCd)로도 조회해 합친다."""
    items = []
    if city.get("areaCode"):   # 옛 지역코드 조회 (법정동 코드를 아직 모를 때만)
        items = api.list_all("areaBasedList2", max_rows, areaCode=city["areaCode"],
                             sigunguCode=city["sigunguCode"], contentTypeId=ctype, arrange="C")
    for code in sorted(ldong or []):
        items += api.list_all("areaBasedList2", max_rows, lDongRegnCd=code[:2], lDongSignguCd=code[2:],
                              contentTypeId=ctype, arrange="C")
    seen, out = set(), []
    for it in items:
        p = to_place(it)
        if p and p["id"] not in seen:
            seen.add(p["id"])
            out.append(p)
    return out


def ldong_codes(places: list[dict]) -> set[str]:
    codes = [a + b if len(a) == 2 and len(b) <= 3 else b for a, b in (p.get("ld") or ("", "") for p in places) if a and b]
    return clean_ldong(c for c in codes if re.fullmatch(r"\d{5}", c))


def clean_ldong(codes) -> set[str]:
    """한 도시의 코드는 한 시·도에 속한다. 데이터 오류로 섞인 다른 시·도 코드(예: 인천에 강원 코드)는 버린다."""
    codes = list(codes)
    if not codes:
        return set()
    top = collections.Counter(c[:2] for c in codes).most_common(1)[0][0]
    return {c for c in codes if c[:2] == top}


# 2026-07 전남광주통합특별시 출범 이후 새 코드(12xxx). 인기 순위 자료가 옛 코드로만 있으면 이름으로 옛 코드를 찾는다.
OLD_SIGUNGU = {
    "동구": "29110", "서구": "29140", "남구": "29155", "북구": "29170", "광산구": "29200",
    "목포시": "46110", "여수시": "46130", "순천시": "46150", "나주시": "46170", "광양시": "46230",
    "담양군": "46710", "곡성군": "46720", "구례군": "46730", "고흥군": "46770", "보성군": "46780",
    "화순군": "46790", "장흥군": "46800", "강진군": "46810", "해남군": "46820", "영암군": "46830",
    "무안군": "46840", "함평군": "46860", "영광군": "46870", "장성군": "46880", "완도군": "46890",
    "진도군": "46900", "신안군": "46910",
}


def code_names(places: list[dict]) -> dict[str, str]:
    """법정 시군구 코드 → 주소 속 시·군·구 이름 (예: 12300 → 북구)"""
    votes: dict[str, collections.Counter] = {}
    for p in places:
        a, b = p.get("ld") or ("", "")
        if not (a and b):
            continue
        code = a + b if len(b) <= 3 else b
        m = re.match(r"\S+\s+(\S+?[시군구])\b", p.get("addr") or "")
        if m:
            votes.setdefault(code, collections.Counter())[m.group(1)] += 1
    return {c: v.most_common(1)[0][0] for c, v in votes.items()}


# ───────────────────────── 인기 순위 (지자체 중심 관광지) ─────────────────────────

def norm_name(s: str) -> str:
    s = re.sub(r"\(.*?\)|\[.*?\]", "", s or "")
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s).lower()


def fetch_hub(api: TourAPI, codes: set[str], names: dict[str, str] | None = None) -> list[dict]:
    """법정 시군구 코드(5자리)별 인기 상위 100곳. 공급 지연을 감안해 2~4개월 전 자료부터 시도.
    광역시처럼 구가 여러 개면 순위가 구마다 따로 매겨지므로, 각 항목에 구 코드(gu)를 붙여 둔다."""
    today = dt.date.today().replace(day=1)
    months = []
    for back in (2, 3, 4, 5):
        y, m = today.year, today.month - back
        while m <= 0:
            y, m = y - 1, m + 12
        months.append(f"{y}{m:02d}")
    out: dict[str, dict] = {}
    for code in sorted(codes):
        tries = [code]
        old = OLD_SIGUNGU.get((names or {}).get(code, "")) if code.startswith("12") else None
        if old:
            tries.append(old)
        rows = []
        for c in tries:
            for ym in ([api.hub_ym] if api.hub_ym else []) + [m for m in months if m != api.hub_ym]:
                rows = api.get_hub(baseYm=ym, areaCd=c[:2], signguCd=c, numOfRows=100, pageNo=1)
                if rows:
                    api.hub_ym = ym
                    break
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
                    "cat": f"{r.get('hubCtgryLclsNm') or ''}/{r.get('hubCtgryMclsNm') or ''}", "gu": code}
            if key not in out or rank < out[key]["rank"]:
                out[key] = item
    return sorted(out.values(), key=lambda x: x["rank"])


CAT_WEIGHT = {"역사관광": 0.6, "자연관광": 0.7, "문화관광": 1.0, "체험관광": 1.0, "레저스포츠": 1.3,
              "기타관광": 1.3, "쇼핑": 1.6}   # 내비 목적지 순위라 생활 시설이 많음 → 명소 성격일수록 앞으로


def hub_score(hub_spot: list[dict]) -> None:
    """순위 점수(낮을수록 좋음) = 구 안 순위 × 분야 가중치 × 구 보정.
    구가 여러 개인 도시는 구마다 1위가 하나씩 있으므로, 역사·자연·문화 명소가 많은 구의 순위를 더 높게 친다."""
    sights = collections.Counter(h.get("gu", "") for h in hub_spot
                                 if re.search(r"역사관광|자연관광|문화관광", h["cat"]))
    top = max(sights.values()) if sights else 1
    for h in hub_spot:
        w = CAT_WEIGHT.get(h["cat"].split("/")[-1], 1.0)
        gu_w = (top / max(sights.get(h.get("gu", ""), 1), 1)) ** 0.7 if len(sights) > 1 else 1.0
        h["score"] = h["rank"] * w * gu_w


# 인기 순위에는 역·터미널·골프장·숙박·영화관도 섞여 있어 관광지 추천에서 뺀다
HUB_NOISE = re.compile(r"(CC$|CC/|GC$|골프|컨트리|리조트|호텔|콘도|수영장|빌리지|빌라|역$|역/|터미널|CGV|시네마|메가박스|"
                       r"경기장|볼파크|야구장|체육관|빙상|백화점|아울렛|몰$|몰/|마트|도매시장|농수산물|병원|주차장|휴게소|"
                       r"톨게이트|IC$|아파트|모텔|펜션|킨텍스|코엑스|벡스코|컨벤션|전시장|공항|아이스링크|노브랜드|이마트|홈플러스|"
                       r"면세점|타워/|축산물시장|수산물도매|EXCO|SETEC|aT센터|대학교$|하우스$)", re.I)
TOURISM_CAT = re.compile(r"문화관광|역사관광|자연관광|체험관광|레저스포츠|기타관광|쇼핑")


DIAG: list[str] = []  # 이름 검색 진단 기록 → data/cache/diag.json


def resolve_hub_spot(api: TourAPI, city: dict, h: dict, regn: str | None) -> dict:
    """순위에는 있는데 관광공사 목록에서 못 찾은 곳: 이름으로 검색해 사진·설명이 있는 항목을 찾고,
    없으면 이름·좌표만으로 추가한다. '한국도로공사/전주수목원'처럼 '/'가 있으면 양쪽을 모두 시도."""
    parts = [x.strip() for x in h["name"].split("/") if x.strip()]
    names = parts[::-1] if len(parts) > 1 else parts           # 뒤쪽(구체적인 이름) 먼저
    keywords = names[:2] + ([names[0][:3]] if len(names) == 1 and len(names[0]) > 4 else [])  # 띄어쓰기 차이 대비
    best = None
    for kw in keywords:
        try:
            params = {"lDongRegnCd": regn} if regn else {"areaCode": city["areaCode"]}
            items = api.get("searchKeyword2", keyword=kw, numOfRows=30, pageNo=1, **params)
            DIAG.append(f"{city['name']} | {kw} | {len(items)}건 | " + ", ".join(
                f"{i.get('title')}({i.get('contenttypeid')})" for i in items[:5]))
        except QuotaError:
            raise
        except RuntimeError as e:
            DIAG.append(f"{city['name']} | {kw} | 오류 {str(e)[:200]}")
            items = []
        for it in items:
            p = to_place(it)
            if not p or not (p["type"] in (CT_SPOT, CT_CULTURE, "28") or (p["type"] == "38" and "시장" in p["name"])):
                continue
            n = norm_name(p["name"])
            ok = any(n == norm_name(x) or (len(min(n, norm_name(x), key=len)) >= 3
                     and (n in norm_name(x) or norm_name(x) in n)) for x in names)
            d = haversine_km(p["lat"], p["lng"], h["lat"], h["lng"])
            if ok and d <= 3 and (best is None or d < best[0]):
                best = (d, p)
        if best:
            return best[1]
    return {"id": f"h{h['code']}", "type": "hub", "name": " ".join(parts), "addr": "", "lat": round(h["lat"], 6),
            "lng": round(h["lng"], 6), "image": "", "thumb": "", "tel": "", "modified": "", "ld": ("", "")}


def apply_curated(api: TourAPI, city: dict, allp: list[dict], ldong: set[str], cache: dict) -> int:
    """data/curated.json에 적어 둔 '대표 명소'를 맨 앞에 고정한다 (내비 순위가 실제 관광 인기와 다른 대도시용).
    목록에 있으면 그대로 쓰고, 없으면 관광공사에서 이름으로 찾아 추가한다."""
    names = load_json(DATA / "curated.json", {}).get(city["name"], [])
    regn = next(iter(sorted(ldong)), "")[:2] or None
    n_ok = 0
    for i, name in enumerate(names):
        nn = norm_name(name)
        def fits(p):
            n = norm_name(p["name"])
            return n == nn or (nn in n and len(n) - len(nn) <= 6)
        hit = min((p for p in allp if fits(p)), key=lambda p: (norm_name(p["name"]) != nn, not p["image"],
                                                                  len(p["name"])), default=None)
        if not hit:
            key = f"cur:{city['id']}:{name}"
            if key not in cache:
                try:
                    params = {"lDongRegnCd": regn} if regn else {"areaCode": city["areaCode"]}
                    items = api.get("searchKeyword2", keyword=name, numOfRows=30, pageNo=1, **params)
                except QuotaError:
                    raise
                except RuntimeError:
                    items = []
                cands = [q for q in (to_place(it) for it in items) if q and fits(q)
                         and (not ldong or ("".join(q["ld"]) if len(q["ld"][1]) <= 3 else q["ld"][1]) in ldong)]
                best = min(cands, key=lambda q: (norm_name(q["name"]) != nn, not q["image"], len(q["name"])), default=None)
                cache[key] = {"at": dt.date.today().isoformat(), "place": best}
            hit = dict(cache[key]["place"]) if cache[key]["place"] else None
            if hit:
                allp.append(hit)
        if hit:
            hit["score"] = 0.01 * (i + 1)
            n_ok += 1
    return n_ok


def match_hub(places: list[dict], hub: list[dict]) -> None:
    """인기 순위 항목 하나에 가장 잘 맞는 장소 '하나'만 연결한다(1:1).
    우선순위: 이름이 똑같은 곳 → 이름 길이 차이가 작은 곳 → 가까운 곳."""
    taken: set[str] = set()
    for h in sorted(hub, key=lambda x: x.get("score", x["rank"])):
        hn = norm_name(h["name"].split("/")[-1]) or norm_name(h["name"])
        cands = []
        for p in places:
            if p["id"] in taken:
                continue
            n = norm_name(p["name"])
            if not n or not hn:
                continue
            same = n == hn
            part = len(min(n, hn, key=len)) >= 3 and (hn in n or n in hn) and abs(len(n) - len(hn)) <= 4
            if not (same or part):
                continue
            d = haversine_km(p["lat"], p["lng"], h["lat"], h["lng"]) if h["lat"] else 0
            if d <= (3.0 if same else 1.5):
                cands.append(((not same, abs(len(n) - len(hn)), d), p))
        if cands:
            p = min(cands, key=lambda c: c[0])[1]
            p["score"] = min(p.get("score", 9e9), h.get("score", h["rank"]))
            taken.add(p["id"])
            h["matched"] = True


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


CAFE = re.compile(r"카페|커피|베이커리|빵|디저트|cafe|coffee", re.I)  # 점심·저녁 자리에는 식당만


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
        cands = [f for f in foods if f["id"] not in used and not CAFE.search(f["name"]) and haversine_km(p["lat"], p["lng"], f["lat"], f["lng"]) <= 2.5]
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
    # 법정동 코드: 도시 목록에 저장된 값이 없으면 음식점 목록(옛 코드로도 잘 잡힘)에서 추출
    ldong = clean_ldong(city.get("ldong") or [])
    if not ldong:
        probe = fetch_places(api, city, CT_FOOD, 100)
        ldong = ldong_codes(probe)
    # 법정동 코드를 알면 그것만으로 조회 (옛 지역코드 조회는 생략해 호출 절약)
    if ldong:
        city_q = {**city, "areaCode": None, "sigunguCode": None}
        spots = fetch_places(api, city_q, CT_SPOT, args.fetch_rows, ldong)
        culture = fetch_places(api, city_q, CT_CULTURE, 150, ldong)
        foods = fetch_places(api, city_q, CT_FOOD, args.fetch_rows, ldong)
    else:
        spots = fetch_places(api, city, CT_SPOT, args.fetch_rows)
        culture = fetch_places(api, city, CT_CULTURE, 150)
        foods = fetch_places(api, city, CT_FOOD, args.fetch_rows)
    allp = spots + culture
    ldong = clean_ldong(ldong | ldong_codes(allp + foods))
    city["ldong"] = sorted(ldong)

    # 인기 순위: TourAPI 항목의 법정 시군구 코드로 '지자체 중심 관광지'를 조회 (30일 캐시)
    hc = caches["hub"]
    hentry = hc.get(city["id"])
    if (hentry and hentry.get("at", "") >= (dt.date.today() - dt.timedelta(days=30)).isoformat()
            and all("gu" in h for h in hentry["items"])):
        hub = [{k: v for k, v in h.items() if k != "matched"} for h in hentry["items"]]  # 지난 실행의 연결 표시 제거
    else:
        codes = set(ldong)
        hub = fetch_hub(api, codes, code_names(allp + foods)) if codes else []
        if hub:
            hc[city["id"]] = {"at": dt.date.today().isoformat(), "items": [dict(h) for h in hub]}
    hub_spot = [h for h in hub if h["cat"].startswith("관광지") and not HUB_NOISE.search(h["name"])
                and not (h["cat"].endswith("쇼핑") and "시장" not in h["name"])]
    hub_score(hub_spot)
    match_hub(allp, hub_spot)

    # 인기 상위인데 연결 안 된 곳은 이름으로 찾아서 추가 (도시별 30일 캐시)
    kc = caches["hubspots"].setdefault(city["id"], {})
    have = {p["id"]: p for p in allp}
    for h in sorted([h for h in hub_spot if not h.get("matched")], key=lambda h: h["score"])[: args.hub_resolve]:
        hit = kc.get("v6:" + h["code"])
        if not hit or hit.get("at", "") < (dt.date.today() - dt.timedelta(days=30)).isoformat():
            regn = next(iter(sorted(ldong)), "")[:2] or None
            hit = {"at": dt.date.today().isoformat(), "place": resolve_hub_spot(api, city, h, regn)}
            kc["v6:" + h["code"]] = hit
        p = dict(hit["place"])
        np_ = norm_name(p["name"])
        def same_place(q):
            nq, d = norm_name(q["name"]), haversine_km(p["lat"], p["lng"], q["lat"], q["lng"])
            return (np_ and nq == np_ and d < 2) or (np_ and nq and (np_ in nq or nq in np_) and d < 0.7)
        dup = have.get(p["id"]) or next((q for q in allp if same_place(q)), None)
        if dup:
            dup["score"] = min(dup.get("score", 9e9), h["score"])
        else:
            p["score"] = h["score"]
            have[p["id"]] = p
            allp.append(p)
        h["matched"] = True
    n_cur = apply_curated(api, city, allp, ldong, caches["hubspots"])
    log(f"   대표 명소 고정 {n_cur}곳 · 후보 관광지 {len(spots)}·문화시설 {len(culture)}·식당 {len(foods)} · 인기 순위 {len(hub_spot)}곳 중 "
        f"{sum(1 for h in hub_spot if h.get('matched'))}곳 연결 · 호출 {api.calls}/{api.hub_calls}")

    # 순위 있는 곳(인기순) → 순위 없는 곳 중 사진 있는 관광지 → 나머지
    for p in allp:
        p.pop("rank", None)
    allp.sort(key=lambda p: (p.get("score", 9e9), not p["image"], p["type"] != CT_SPOT))
    max_spots = args.max_spots + (20 if len(ldong) > 3 else 0)   # 구가 많은 광역시는 더 많이
    places = allp[:max_spots]
    for i, p in enumerate([p for p in places if "score" in p], 1):
        p["rank"] = i   # 화면에 보이는 '인기 n위' = 도시 안 순서
    for p in places:
        p.setdefault("desc", "")
        p.setdefault("videos", [])

    # 개요(설명): 캐시 우선, 없으면 상위 일부만 detailCommon2 호출
    ov = caches["overview"]
    for p in places[: args.overview_top]:
        if p["id"].startswith("h"):
            continue
        if p["id"] not in ov and budget["overview"] > 0:
            try:
                d = api.get("detailCommon2", contentId=p["id"])
                ov[p["id"]] = clean_text((d[0] if d else {}).get("overview"), 160)
            except QuotaError:
                raise
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
    ap.add_argument("--hub-resolve", type=int, default=12, help="연결 안 된 인기 관광지를 이름으로 찾을 최대 개수")
    ap.add_argument("--batch", type=int, default=30, help="이번 실행에서 처리할 도시 수(오래된 순)")
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

    caches = {name: load_json(CACHE_DIR / f"{name}.json", {}) for name in ("overview", "videos", "courses", "hub", "hubspots")}
    budget = {"overview": args.overview_budget, "youtube": args.youtube_budget, "claude": args.claude_budget}

    for city in targets:
        try:
            out = process_city(city, api, args, caches, budget)
        except RuntimeError as e:
            log("   건너뜀:", e)
            if isinstance(e, QuotaError) or "한도" in str(e) or "인증" in str(e):
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

    save_json(CACHE_DIR / "diag.json", {"at": now_iso(), "lines": DIAG[:300]})
    log(f"완료 · 인기순위 호출 {api.hub_calls}회 · TourAPI 호출 {api.calls}회 · 남은 YouTube 예산 {max(budget['youtube'], 0)}")


if __name__ == "__main__":
    main()
