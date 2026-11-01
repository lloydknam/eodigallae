"""전국 축제·공연행사 정보. 두 데이터를 합쳐 도시별로 나눠 data/festivals.json에 저장한다.
  1) 한국관광공사 TourAPI 축제공연행사정보 (TOURAPI_KEY 재사용, 전국을 법정동 코드로 도시 매칭)
  2) 전국문화축제표준데이터 (FESTIVAL_STD_KEY, 공공데이터포털. 위도·경도가 있어 가장 가까운 도시로 매칭)
좌표가 있는 표준데이터를 더 정확한 것으로 보고, 같은 축제가 겹치면 표준데이터 쪽을 남긴다."""
import json, math, os, re, sys, urllib.parse, urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOUR_BASE = "https://apis.data.go.kr/B551011/KorService2"
STD_BASE = "https://api.data.go.kr/openapi/tn_pubr_public_cltur_fstvl_api"
DAYS_AHEAD = 180


def log(*a):
    print(*a, file=sys.stderr)


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def norm(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", str(s or "")).lower()


# ── 1) TourAPI 축제공연행사정보 ──
def tour_call(key: str, page: int) -> dict:
    today = date.today().strftime("%Y%m%d")
    end = (date.today() + timedelta(days=DAYS_AHEAD)).strftime("%Y%m%d")
    q = {"serviceKey": key, "MobileOS": "ETC", "MobileApp": "eodigallae", "_type": "json",
         "numOfRows": "200", "pageNo": str(page), "arrange": "A",
         "eventStartDate": today, "eventEndDate": end}
    url = f"{TOUR_BASE}/searchFestival2?{urllib.parse.urlencode(q)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_tour(key: str) -> list[dict]:
    out, page = [], 1
    while True:
        js = tour_call(key, page)
        body = js.get("response", {}).get("body", {})
        raw = body.get("items", {}).get("item")
        items = raw if isinstance(raw, list) else [raw] if raw else []
        out += items
        total = int(body.get("totalCount") or 0)
        if not items or len(out) >= total or page > 10:
            break
        page += 1
    return out


def build_ldong_index(cities: list[dict]) -> dict[str, dict]:
    idx = {}
    for c in cities:
        for code in c.get("ldong") or []:
            idx[code] = c
    return idx


def build_area_index(cities: list[dict]) -> dict[tuple, dict]:
    idx = {}
    for c in cities:
        if c.get("areaCode"):
            idx[(str(c["areaCode"]), str(c.get("sigunguCode") or ""))] = c
    return idx


def match_city_tour(it: dict, ldong_idx: dict, area_idx: dict) -> dict | None:
    regn, signgu = str(it.get("lDongRegnCd") or ""), str(it.get("lDongSignguCd") or "")
    if regn and signgu:
        c = ldong_idx.get(regn + signgu)
        if c:
            return c
        # 세종처럼 하위 구역이 없는 곳은 TourAPI가 시군구 코드에 광역 코드를 그대로 반복해서 보낸다
        # (예: lDongRegnCd=36110, lDongSignguCd=36110) — 이때는 광역 코드 하나만으로 다시 찾는다
        if signgu == regn:
            c = ldong_idx.get(regn)
            if c:
                return c
    area, sgg = str(it.get("areacode") or ""), str(it.get("sigungucode") or "")
    if area:
        c = area_idx.get((area, sgg)) or area_idx.get((area, ""))
        if c:
            return c
    return None


def tour_entry(it: dict, city: dict) -> dict:
    return {
        "id": f"tour-{it.get('contentid')}", "title": (it.get("title") or "").strip(),
        "start": it.get("eventstartdate", ""), "end": it.get("eventenddate", ""),
        "addr": (it.get("addr1") or "").strip(), "tel": (it.get("tel") or "").strip(),
        "lat": float(it["mapy"]) if it.get("mapy") else None,
        "lng": float(it["mapx"]) if it.get("mapx") else None,
        "image": it.get("firstimage") or it.get("firstimage2") or None,
        "homepage": None, "cityId": city["id"], "city": city["name"], "source": "tour",
    }


# ── 2) 전국문화축제표준데이터 ──
def std_call(key: str, page: int) -> dict:
    q = {"serviceKey": key, "pageNo": str(page), "numOfRows": "500", "type": "json"}
    url = f"{STD_BASE}?{urllib.parse.urlencode(q)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def std_fetch(key: str) -> list[dict]:
    out, page = [], 1
    while True:
        js = std_call(key, page)
        body = js.get("body", {})
        raw = body.get("items", {}).get("item")
        items = raw if isinstance(raw, list) else [raw] if raw else []
        out += items
        total = int(body.get("totalCount") or 0)
        if not items or len(out) >= total or page > 20:
            break
        page += 1
    return out


# 표준데이터 중 위도·경도가 비어 있는 항목을 위한 주소 텍스트 매칭(시도 축약형 → cities.json의 province 값)
PROV_SHORT = {
    "서울특별시": "서울", "서울": "서울", "부산광역시": "부산", "부산": "부산",
    "대구광역시": "대구", "대구": "대구", "인천광역시": "인천", "인천": "인천",
    "광주광역시": "광주", "광주": "광주", "대전광역시": "대전", "대전": "대전",
    "울산광역시": "울산", "울산": "울산", "세종특별자치시": "세종특별자치시", "세종": "세종특별자치시",
    "경기도": "경기도", "경기": "경기도",
    "강원특별자치도": "강원특별자치도", "강원도": "강원특별자치도", "강원": "강원특별자치도",
    "충청북도": "충청북도", "충북": "충청북도", "충청남도": "충청남도", "충남": "충청남도",
    "전북특별자치도": "전북특별자치도", "전라북도": "전북특별자치도", "전북": "전북특별자치도",
    "전라남도": "전라남도", "전남": "전라남도",
    "경상북도": "경상북도", "경북": "경상북도", "경상남도": "경상남도", "경남": "경상남도",
    "제주특별자치도": "제주특별자치도", "제주도": "제주특별자치도", "제주": "제주특별자치도",
}


def build_addr_index(cities: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for c in cities:
        idx.setdefault(c["province"], []).append(c)
    return idx


def match_by_address(addr: str, addr_idx: dict[str, list[dict]]) -> dict | None:
    """위도·경도가 없는 표준데이터용: 주소 문자열에서 시도→시군구 이름을 찾아 매칭한다."""
    if not addr:
        return None
    province = None
    for token, full in sorted(PROV_SHORT.items(), key=lambda kv: -len(kv[0])):
        if token in addr:
            province = full
            break
    if not province:
        return None
    cands = addr_idx.get(province) or []
    # 시군구 이름이 가장 길게 일치하는 쪽(예: "고성군"이 "고성"보다 우선)을 고른다
    best, best_len = None, 0
    for c in cands:
        name = c["name"]
        if name == province:
            continue
        if name in addr and len(name) > best_len:
            best, best_len = c, len(name)
    if best:
        return best
    # 시군구 이름이 안 보이면(광역시 등 단일 도시) 그 시도 자체를 가리키는 항목으로
    for c in cands:
        if c["name"] == province:
            return c
    return None


def nearest_city(lat: float, lng: float, cities: list[dict]) -> dict | None:
    best, best_d = None, 1e9
    for c in cities:
        center = c.get("center")
        if not center:
            continue
        d = haversine_km(lat, lng, center[0], center[1])
        if d < best_d:
            best, best_d = c, d
    return best if best_d < 60 else None  # 60km 넘게 떨어지면 매칭하지 않는다 (잘못된 좌표 방지)


def std_entry(it: dict, city: dict) -> dict:
    start = (it.get("fstvlStartDate") or "").replace("-", "")
    end = (it.get("fstvlEndDate") or "").replace("-", "")
    return {
        "id": f"std-{it.get('insttCode')}-{norm(it.get('fstvlNm'))}-{start}", "title": (it.get("fstvlNm") or "").strip(),
        "start": start, "end": end, "addr": (it.get("rdnmadr") or it.get("lnmadr") or "").strip(),
        "tel": (it.get("phoneNumber") or "").strip(),
        "lat": float(it["latitude"]) if it.get("latitude") else None,
        "lng": float(it["longitude"]) if it.get("longitude") else None,
        "image": None, "homepage": (it.get("homepageUrl") or "").strip() or None,
        "cityId": city["id"], "city": city["name"], "source": "std",
    }


def dedupe(items: list[dict]) -> list[dict]:
    """제목이 같고 시작일이 사흘 안으로 겹치면 표준데이터 쪽(source=std)을 남긴다."""
    by_key: dict[tuple, dict] = {}
    for it in items:
        key = (norm(it["title"])[:12], it["cityId"])
        prev = by_key.get(key)
        if not prev:
            by_key[key] = it
            continue
        close = abs(int(it["start"] or 0) - int(prev["start"] or 0)) <= 3 if it["start"] and prev["start"] else True
        if close and it["source"] == "std":
            by_key[key] = it
        elif not close:
            by_key[(key[0], key[1], it["start"])] = it  # 겹치지 않으면 둘 다 남긴다
    return list(by_key.values())


def main():
    tour_key = os.environ.get("TOURAPI_KEY", "").strip()
    std_key = os.environ.get("FESTIVAL_STD_KEY", "").strip()
    if not tour_key and not std_key:
        log("TOURAPI_KEY, FESTIVAL_STD_KEY가 모두 없어요."); sys.exit(1)
    cities = json.loads((ROOT / "data" / "cities.json").read_text(encoding="utf-8"))["cities"]
    today = date.today().strftime("%Y%m%d")
    out: list[dict] = []

    if tour_key:
        ldong_idx, area_idx = build_ldong_index(cities), build_area_index(cities)
        raw = fetch_tour(tour_key)
        unmatched, misses = 0, []
        for it in raw:
            if not it.get("title") or (it.get("eventenddate") and it["eventenddate"] < today):
                continue
            city = match_city_tour(it, ldong_idx, area_idx)
            if not city:
                unmatched += 1
                misses.append(f"{it.get('title','')[:20]} (ldong={it.get('lDongRegnCd','')}{it.get('lDongSignguCd','')} area={it.get('areacode','')}/{it.get('sigungucode','')})")
                continue
            out.append(tour_entry(it, city))
        log(f"TourAPI 축제 {sum(1 for x in out if x['source'] == 'tour')}건 매칭 (실패 {unmatched}건, 전체 {len(raw)}건)")
        if misses:
            log("TourAPI 매칭 실패 목록: " + " | ".join(misses[:30]))

    if std_key:
        addr_idx = build_addr_index(cities)
        raw = std_fetch(std_key)
        unmatched, misses = 0, []
        for it in raw:
            end = (it.get("fstvlEndDate") or "").replace("-", "")
            if not it.get("fstvlNm") or (end and end < today):
                continue
            lat, lng = it.get("latitude"), it.get("longitude")
            city = nearest_city(float(lat), float(lng), cities) if lat and lng else None
            if not city:
                addr = (it.get("rdnmadr") or it.get("lnmadr") or "")
                city = match_by_address(addr, addr_idx)
            if not city:
                unmatched += 1
                misses.append(f"{it.get('fstvlNm','')[:20]} ({it.get('latitude','')},{it.get('longitude','')})")
                continue
            out.append(std_entry(it, city))
        log(f"표준데이터 축제 {sum(1 for x in out if x['source'] == 'std')}건 매칭 (실패 {unmatched}건, 전체 {len(raw)}건)")
        if misses:
            log("표준데이터 매칭 실패 목록: " + " | ".join(misses[:30]))

    out = dedupe(out)
    out.sort(key=lambda x: x["start"] or "99999999")
    payload = {"updatedAt": date.today().isoformat(), "count": len(out), "items": out}
    (ROOT / "data" / "festivals.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"합쳐서 {len(out)}건 저장")


if __name__ == "__main__":
    main()
