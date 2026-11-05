"""한국문화정보원 한눈에보는문화정보조회서비스(공공데이터포털, CULTURE_KEY).
문체부·산하기관이 생산하는 전국 공연·전시·문화행사 정보를 기간별로 받아 도시별로 나눠
data/culture.json에 저장한다. 축제지도(TourAPI/전국문화축제표준데이터, festival.py)와는 출처가
다른 별도 데이터라 지금은 분리해서 모은다 — 나중에 한 메뉴로 합칠지는 추후 검토.

주의: 이 API는 공공데이터포털 문서에 정확한 응답 필드명이 공개돼 있지 않아(활용가이드 zip만
있음), 아래 필드 매핑은 이 API를 실제로 널리 쓰는 사례들을 참고한 추정치다. CULTURE_KEY를
발급받아 처음 실행하면 로그에 첫 응답의 원본 키 목록을 찍어 두니, 실제 필드명이 다르면
그 로그를 보고 FIELD_MAP만 고치면 된다.
"""
import json, os, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import festival  # 주소 → 도시 매칭 로직(PROV_SHORT, build_addr_index, match_by_address) 재사용

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://apis.data.go.kr/B553457/nopenapi/rest/publicperformancedisplays/period"
DAYS_AHEAD = 120

# 이 API가 실제로 쓰는 필드명으로 보이는 후보들(여러 변형을 같이 받아 가장 먼저 걸리는 걸 쓴다).
# CULTURE_KEY 발급 후 첫 실행 로그의 "응답 원본 키" 목록을 보고 필요하면 조정한다.
FIELD_MAP = {
    "title": ["title", "subTitle", "perforTitle"],
    "start": ["startDate", "strtDate", "beginDate"],
    "end": ["endDate", "endDt"],
    "place": ["place", "spot", "realmName"],
    "area": ["area", "realmName"],
    "lat": ["gpsY", "latitude", "lat"],
    "lng": ["gpsX", "longitude", "lng"],
    "thumbnail": ["thumbnail", "imgUrl", "image"],
    "url": ["url", "detailUrl", "relateUrl"],
    "seq": ["seq", "id"],
}


def log(*a):
    print(*a, file=sys.stderr)


def save_json(path: Path, obj, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":") if compact else None,
                     indent=None if compact else 1)
    path.write_text(txt, encoding="utf-8")


def pick(it: dict, key: str):
    for name in FIELD_MAP[key]:
        v = it.get(name)
        if v not in (None, ""):
            return v
    return None


def call(key: str, frm: str, to: str, page: int) -> str:
    q = {"serviceKey": key, "from": frm, "to": to, "cPage": str(page), "rows": "100"}
    url = f"{BASE}?{urllib.parse.urlencode(q)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse(body: str) -> list[dict]:
    body = body.strip()
    if body.startswith("{"):
        js = json.loads(body)
        # 흔히 쓰는 두 형태(response.msgBody.perforList / response.body.items.item)를 모두 시도
        msg = js.get("response", js)
        for path in (("msgBody", "perforList"), ("body", "items", "item")):
            cur = msg
            for p in path:
                cur = cur.get(p) if isinstance(cur, dict) else None
                if cur is None:
                    break
            if cur:
                return cur if isinstance(cur, list) else [cur]
        return []
    root = ET.fromstring(body)
    return [{child.tag: (child.text or "").strip() for child in el} for el in root.iter()
            if list(el) and el.tag not in ("response", "msgBody", "msgHeader")]


def fetch_all(key: str) -> list[dict]:
    today = date.today().strftime("%Y%m%d")
    end = (date.today() + timedelta(days=DAYS_AHEAD)).strftime("%Y%m%d")
    out, page, logged_keys = [], 1, False
    while True:
        body = call(key, today, end, page)
        items = parse(body)
        if items and not logged_keys:
            log("응답 원본 키 목록(첫 항목):", sorted(items[0].keys()))
            logged_keys = True
        if not items:
            break
        out += items
        if len(items) < 100 or page > 10:
            break
        page += 1
    return out


def to_entry(it: dict, city: dict) -> dict:
    seq = pick(it, "seq") or ""
    return {
        "id": f"culture-{seq}", "title": str(pick(it, "title") or "").strip(),
        "start": str(pick(it, "start") or "").replace("-", ""), "end": str(pick(it, "end") or "").replace("-", ""),
        "place": str(pick(it, "place") or "").strip(),
        "lat": float(pick(it, "lat")) if pick(it, "lat") else None,
        "lng": float(pick(it, "lng")) if pick(it, "lng") else None,
        "image": pick(it, "thumbnail"), "homepage": pick(it, "url"),
        "cityId": city["id"], "city": city["name"],
    }


def main():
    key = os.environ.get("CULTURE_KEY", "").strip()
    if not key:
        log("CULTURE_KEY가 없어요."); sys.exit(1)
    cities = json.loads((ROOT / "data" / "cities.json").read_text(encoding="utf-8"))["cities"]
    addr_idx = festival.build_addr_index(cities)

    raw = fetch_all(key)
    out, unmatched = [], 0
    for it in raw:
        title = pick(it, "title")
        if not title:
            continue
        place = str(pick(it, "place") or "")
        city = festival.match_by_address(place, addr_idx)
        if not city:
            lat, lng = pick(it, "lat"), pick(it, "lng")
            if lat and lng:
                city = festival.nearest_city(float(lat), float(lng), cities)
        if not city:
            unmatched += 1
            continue
        out.append(to_entry(it, city))

    payload = {"updatedAt": date.today().isoformat(), "count": len(out), "items": out}
    save_json(ROOT / "data" / "culture.json", payload, compact=True)
    log(f"문체부 문화행사 {len(out)}건 저장 (전체 {len(raw)}건, 도시 매칭 실패 {unmatched}건)")


if __name__ == "__main__":
    main()
