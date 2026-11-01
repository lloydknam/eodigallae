"""전국 축제·공연행사 정보 (한국관광공사 TourAPI searchFestival2, 기존 TOURAPI_KEY 재사용).
오늘부터 앞으로 180일 안에 열리거나 진행 중인 축제를 모아 도시별로 나눠 data/festivals.json에 저장한다."""
import json, os, sys, urllib.parse, urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://apis.data.go.kr/B551011/KorService2"
DAYS_AHEAD = 180


def log(*a):
    print(*a, file=sys.stderr)


def call(key: str, page: int) -> dict:
    today = date.today().strftime("%Y%m%d")
    end = (date.today() + timedelta(days=DAYS_AHEAD)).strftime("%Y%m%d")
    q = {"serviceKey": key, "MobileOS": "ETC", "MobileApp": "eodigallae", "_type": "json",
         "numOfRows": "200", "pageNo": str(page), "arrange": "A",
         "eventStartDate": today, "eventEndDate": end}
    url = f"{BASE}/searchFestival2?{urllib.parse.urlencode(q)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_all(key: str) -> list[dict]:
    out, page = [], 1
    while True:
        js = call(key, page)
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


def match_city(it: dict, ldong_idx: dict, area_idx: dict) -> dict | None:
    regn, signgu = str(it.get("lDongRegnCd") or ""), str(it.get("lDongSignguCd") or "")
    if regn and signgu:
        c = ldong_idx.get(regn + signgu)
        if c:
            return c
    area, sgg = str(it.get("areacode") or ""), str(it.get("sigungucode") or "")
    if area:
        c = area_idx.get((area, sgg)) or area_idx.get((area, ""))
        if c:
            return c
    return None


def to_entry(it: dict, city: dict) -> dict:
    return {
        "id": it.get("contentid"), "title": (it.get("title") or "").strip(),
        "start": it.get("eventstartdate", ""), "end": it.get("eventenddate", ""),
        "addr": (it.get("addr1") or "").strip(), "tel": (it.get("tel") or "").strip(),
        "lat": float(it["mapy"]) if it.get("mapy") else None,
        "lng": float(it["mapx"]) if it.get("mapx") else None,
        "image": it.get("firstimage") or it.get("firstimage2") or None,
        "cityId": city["id"], "city": city["name"],
    }


def main():
    key = os.environ.get("TOURAPI_KEY", "").strip()
    if not key:
        log("TOURAPI_KEY가 없어요."); sys.exit(1)
    cities = json.loads((ROOT / "data" / "cities.json").read_text(encoding="utf-8"))["cities"]
    ldong_idx, area_idx = build_ldong_index(cities), build_area_index(cities)
    raw = fetch_all(key)
    today = date.today().strftime("%Y%m%d")
    out, unmatched = [], 0
    for it in raw:
        if not it.get("title") or (it.get("eventenddate") and it["eventenddate"] < today):
            continue
        city = match_city(it, ldong_idx, area_idx)
        if not city:
            unmatched += 1
            continue
        out.append(to_entry(it, city))
    out.sort(key=lambda x: x["start"])
    payload = {"updatedAt": date.today().isoformat(), "count": len(out), "items": out}
    (ROOT / "data" / "festivals.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"축제 {len(out)}건 저장 (도시 매칭 실패 {unmatched}건, 전체 {len(raw)}건)")


if __name__ == "__main__":
    main()
