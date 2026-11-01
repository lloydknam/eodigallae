"""전국시티투어정보표준데이터 (data.go.kr 15025456, api.data.go.kr 표준 API, CITYTOUR_KEY 사용).
전국 시티투어 코스를 받아 도시별로 나눠 data/citytour.json에 저장한다."""
import json, os, re, sys, urllib.parse, urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://api.data.go.kr/openapi/tn_pubr_public_city_tour_api"

PROV_ALIAS = {
    "강원도": "강원특별자치도", "전라북도": "전북특별자치도",
    "서울특별시": "서울", "인천광역시": "인천", "대전광역시": "대전", "대구광역시": "대구",
    "광주광역시": "광주", "부산광역시": "부산", "울산광역시": "울산", "세종특별자치시": "세종특별자치시",
}


def log(*a):
    print(*a, file=sys.stderr)


def fetch_all(key: str) -> list[dict]:
    q = {"serviceKey": key, "pageNo": "1", "numOfRows": "500", "type": "json"}
    url = f"{BASE}?{urllib.parse.urlencode(q)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        js = json.loads(r.read().decode("utf-8", "replace"))
    raw = js.get("body", {}).get("items", {}).get("item")
    return raw if isinstance(raw, list) else [raw] if raw else []


def build_index(cities: list[dict]) -> dict[tuple, dict]:
    idx = {}
    for c in cities:
        idx[(c["province"], c["name"])] = c
        idx.setdefault((c["province"], None), c)  # 시도 전체를 가리키는 항목용 (광역시 등)
    return idx


def match_city(it: dict, idx: dict) -> dict | None:
    prov = PROV_ALIAS.get(it.get("ctprvnNm", ""), it.get("ctprvnNm", ""))
    signgu = (it.get("signguNm") or "").strip() or None
    if signgu:
        c = idx.get((prov, signgu))
        if c:
            return c
        base = re.sub(r"(특별자치시|특별자치도|광역시|특별시)$", "", signgu)
        c = idx.get((prov, base))
        if c:
            return c
    return idx.get((prov, None))


def clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace("+", " · ")).strip()


def to_entry(it: dict, city: dict) -> dict:
    return {
        "course": clean(it.get("cityTourCourse")), "method": clean(it.get("operMthd")),
        "schedule": clean(it.get("operHhmm")), "open": clean(it.get("operOpenHhmm")),
        "close": clean(it.get("operCloseHhmm")), "board": clean(it.get("brdngPlaceNm")),
        "courseInfo": clean(it.get("courseInfo")), "nearby": clean(it.get("cfrTursmInfo")),
        "fee": clean(it.get("useCharge")), "feeNote": clean(it.get("useChargeAdiInfo")),
        "contact": clean(it.get("cityTourRefrnc")), "homepage": (it.get("homepageUrl") or "").strip(),
        "org": clean(it.get("institutionNm")), "cityId": city["id"], "city": city["name"],
    }


def main():
    key = os.environ.get("CITYTOUR_KEY", "").strip()
    if not key:
        log("CITYTOUR_KEY가 없어요."); sys.exit(1)
    cities = json.loads((ROOT / "data" / "cities.json").read_text(encoding="utf-8"))["cities"]
    idx = build_index(cities)
    raw = fetch_all(key)
    out, unmatched = [], 0
    for it in raw:
        if not it.get("cityTourCourse"):
            continue
        city = match_city(it, idx)
        if not city:
            unmatched += 1
            continue
        out.append(to_entry(it, city))
    payload = {"updatedAt": date.today().isoformat(), "count": len(out), "items": out}
    (ROOT / "data" / "citytour.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"시티투어 {len(out)}건 저장 (도시 매칭 실패 {unmatched}건, 전체 {len(raw)}건)")


if __name__ == "__main__":
    main()
