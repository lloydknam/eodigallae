"""한국문화정보원 한눈에보는문화정보조회서비스(공공데이터포털, CULTURE_KEY).
문체부·산하기관이 생산하는 전국 공연·전시·문화행사 정보를 기간별로 받아 도시별로 나눠
data/culture.json에 저장한다. 축제지도(TourAPI/전국문화축제표준데이터, festival.py)와는 출처가
다른 별도 데이터라 지금은 분리해서 모은다 — 나중에 한 메뉴로 합칠지는 추후 검토.
"""
import html, json, os, sys, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import festival  # 주소 → 도시 매칭 로직(PROV_SHORT, build_addr_index, match_by_address) 재사용

ROOT = Path(__file__).resolve().parent.parent
# 공공데이터포털 상세페이지 기준 base는 cultureinfo. 오퍼레이션 경로가 확실치 않아
# 후보를 순서대로 시도해서 NO_OPENAPI_SERVICE_ERROR가 아닌 첫 경로를 쓴다.
BASE_CANDIDATES = [
    "https://apis.data.go.kr/B553457/cultureinfo/period2",
    "https://apis.data.go.kr/B553457/cultureinfo/period",
    "https://apis.data.go.kr/B553457/nopenapi/rest/publicperformancedisplays/period",
]
BASE = BASE_CANDIDATES[0]
DAYS_AHEAD = 120
ROWS = 100
MAX_PAGES = 30

# 실제 응답 확인 결과(2026-11): <response><header/><body><totalCount/><items><item>…</item></items></body></response>
# item 필드: serviceName, seq, title, startDate, endDate, place, realmName, area, sigungu, thumbnail, gpsX, gpsY
FIELD_MAP = {
    "title": ["title"],
    "start": ["startDate"],
    "end": ["endDate"],
    "place": ["place"],
    "lat": ["gpsY"],
    "lng": ["gpsX"],
    "thumbnail": ["thumbnail"],
    "seq": ["seq"],
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


def _get(base: str, q: dict) -> str:
    url = f"{base}?{urllib.parse.urlencode(q)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def call(key: str, frm: str, to: str, page: int) -> str:
    global BASE
    q = {"serviceKey": key, "from": frm, "to": to, "PageNo": str(page), "numOfrows": str(ROWS)}
    try:
        return _get(BASE, q)
    except urllib.error.HTTPError as e:
        if e.code != 400 or "NO_OPENAPI_SERVICE_ERROR" not in e.read().decode("utf-8", "replace"):
            raise
    # 경로가 틀린 경우에만 다른 후보로 넘어간다
    for cand in BASE_CANDIDATES:
        if cand == BASE:
            continue
        try:
            body = _get(cand, q)
        except urllib.error.HTTPError:
            continue
        BASE = cand
        log("사용할 엔드포인트:", cand)
        return body
    raise RuntimeError("모든 엔드포인트 후보가 실패했어요")


def parse(body: str) -> tuple[list[dict], int]:
    root = ET.fromstring(body)
    code = root.findtext("./header/resultCode", "")
    if code and code != "00":
        raise RuntimeError(f"API 결과 코드 {code}: {root.findtext('./header/resultMsg', '')}")
    total = int(root.findtext("./body/totalCount", "0") or 0)
    items = [{c.tag: (c.text or "").strip() for c in el} for el in root.iter("item")]
    return items, total


def fetch_all(key: str) -> list[dict]:
    today = date.today().strftime("%Y%m%d")
    end = (date.today() + timedelta(days=DAYS_AHEAD)).strftime("%Y%m%d")
    out, page, logged_keys = [], 1, False
    while page <= MAX_PAGES:
        items, total = parse(call(key, today, end, page))
        if items and not logged_keys:
            log("응답 항목 키:", sorted(items[0].keys()))
            logged_keys = True
        out += items
        log(f"페이지 {page}: {len(items)}건 (전체 {total}건)")
        if not items or page * ROWS >= total:
            break
        page += 1
    return out


def to_entry(it: dict, city: dict) -> dict:
    seq = pick(it, "seq") or ""
    lat, lng = pick(it, "lat"), pick(it, "lng")
    return {
        "id": f"culture-{seq}",
        "title": html.unescape(str(pick(it, "title") or "")).strip(),  # 원본이 이중 이스케이프돼 있음
        "start": str(pick(it, "start") or "").replace("-", ""),
        "end": str(pick(it, "end") or "").replace("-", ""),
        "place": html.unescape(str(pick(it, "place") or "")).strip(),
        "lat": float(lat) if lat else None,
        "lng": float(lng) if lng else None,
        "image": pick(it, "thumbnail"),
        "homepage": None,
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
        if not pick(it, "title"):
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
