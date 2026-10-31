#!/usr/bin/env python3
"""인파지도(서울): 서울시 실시간 인구데이터(주요 121장소, 통신 데이터 기반 추정)를 모아 data/live/seoul.json 에 저장.

- 서울시 서버가 https를 지원하지 않아 앱이 직접 부를 수 없으므로 GitHub Actions가 30분마다 모아 둔다.
- 장소 목록은 코드(POI001~)를 차례로 물어 알아내고 data/live/places.json 에 기억한다(7일마다 다시 확인).
- 위치: 손으로 적어 둔 대략 좌표 → 없으면 OpenStreetMap(Nominatim)에서 한 번 찾아 기억.
- SEOUL_API_KEY가 없으면 견본 키로 '광화문·덕수궁' 한 곳만 받아 형식을 확인한다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "live"
KST = dt.timezone(dt.timedelta(hours=9))
BASE = "http://openapi.seoul.go.kr:8088/{key}/json/citydata_ppltn/1/5/{area}"
S = requests.Session()
S.headers["User-Agent"] = "eodigallae/1.0 (github.com/lloydknam/eodigallae)"

# 대략 좌표 (이름 일부 → 위도, 경도). 지도 위 '어디쯤'을 보여주는 용도라 정밀하지 않아도 된다.
COORDS = {
    "강남MICE": (37.5118, 127.0592), "동대문관광특구": (37.5687, 127.0090), "명동": (37.5636, 126.9850),
    "이태원관광특구": (37.5345, 126.9946), "잠실관광특구": (37.5133, 127.1001), "종로청계": (37.5700, 126.9920),
    "홍대관광특구": (37.5563, 126.9236), "경복궁": (37.5796, 126.9770), "광화문덕수궁": (37.5700, 126.9768),
    "보신각": (37.5699, 126.9831), "암사동": (37.5603, 127.1300), "창덕궁종묘": (37.5767, 126.9930),
    "가산디지털단지역": (37.4816, 126.8827), "강남역": (37.4979, 127.0276), "건대입구역": (37.5404, 127.0692),
    "고덕역": (37.5550, 127.1541), "고속터미널역": (37.5049, 127.0049), "교대역": (37.4934, 127.0142),
    "구로디지털단지역": (37.4852, 126.9015), "구로역": (37.5030, 126.8820), "군자역": (37.5571, 127.0794),
    "대림역": (37.4932, 126.8958), "동대문역": (37.5714, 127.0098), "뚝섬역": (37.5474, 127.0473),
    "미아사거리역": (37.6133, 127.0301), "발산역": (37.5590, 126.8378), "사당역": (37.4765, 126.9816),
    "삼각지역": (37.5347, 126.9731), "서울대입구역": (37.4812, 126.9527), "마곡나루역": (37.5667, 126.8272),
    "서울식물원": (37.5694, 126.8350), "서울역": (37.5547, 126.9707), "선릉역": (37.5045, 127.0490),
    "성신여대입구역": (37.5926, 127.0164), "수유역": (37.6380, 127.0257), "논현역": (37.5110, 127.0214),
    "신논현역": (37.5046, 127.0251), "신도림역": (37.5088, 126.8912), "신림역": (37.4842, 126.9297),
    "신촌이대역": (37.5582, 126.9411), "신촌": (37.5598, 126.9426), "양재역": (37.4844, 127.0343),
    "역삼역": (37.5006, 127.0364), "연신내역": (37.6190, 126.9210), "오목교역": (37.5245, 126.8750),
    "목동운동장": (37.5306, 126.8813), "왕십리역": (37.5612, 127.0373), "용산역": (37.5299, 126.9648),
    "이태원역": (37.5345, 126.9946), "장지역": (37.4787, 127.1262), "장한평역": (37.5614, 127.0647),
    "천호역": (37.5386, 127.1236), "총신대입구": (37.4874, 126.9820), "이수역": (37.4862, 126.9819),
    "충정로역": (37.5600, 126.9636), "합정역": (37.5495, 126.9139), "혜화역": (37.5822, 127.0019),
    "홍대입구역": (37.5572, 126.9245), "회기역": (37.5898, 127.0577), "신정네거리역": (37.5200, 126.8530),
    "잠실새내역": (37.5116, 127.0863), "잠실역": (37.5133, 127.1001), "남구로역": (37.4860, 126.8873),
    "노량진": (37.5133, 126.9426), "쌍문역": (37.6486, 127.0347), "청량리": (37.5803, 127.0447),
    "가락시장": (37.4930, 127.1180), "가로수길": (37.5207, 127.0230), "광장시장": (37.5701, 126.9996),
    "김포공항": (37.5622, 126.8011), "덕수궁길정동길": (37.5658, 126.9740), "북촌한옥마을": (37.5826, 126.9837),
    "서촌": (37.5797, 126.9700), "성수카페거리": (37.5446, 127.0557), "압구정로데오": (37.5272, 127.0405),
    "여의도": (37.5219, 126.9245), "연남동": (37.5620, 126.9235), "영등포타임스퀘어": (37.5170, 126.9033),
    "용리단길": (37.5320, 126.9705), "앤틱가구거리": (37.5340, 126.9960), "인사동": (37.5741, 126.9849),
    "창동": (37.6531, 127.0477), "청담동명품거리": (37.5250, 127.0450), "해방촌": (37.5420, 126.9860),
    "경리단길": (37.5390, 126.9890), "DDP": (37.5665, 127.0093), "동대문디자인플라자": (37.5665, 127.0093),
    "DMC": (37.5770, 126.8900), "디지털미디어시티": (37.5770, 126.8900), "북창동": (37.5626, 126.9790),
    "남대문시장": (37.5591, 126.9773), "익선동": (37.5745, 126.9895), "망원": (37.5560, 126.9010),
    "강서한강공원": (37.5876, 126.8160), "고척돔": (37.4982, 126.8671), "광나루한강공원": (37.5480, 127.1200),
    "광화문광장": (37.5725, 126.9769), "국립중앙박물관": (37.5240, 126.9803), "용산가족공원": (37.5230, 126.9840),
    "난지한강공원": (37.5670, 126.8750), "남산공원": (37.5512, 126.9882), "노들섬": (37.5176, 126.9584),
    "뚝섬한강공원": (37.5292, 127.0698), "망원한강공원": (37.5545, 126.8960), "반포한강공원": (37.5100, 126.9960),
    "북서울꿈의숲": (37.6205, 127.0410), "불광천": (37.5850, 126.9040), "서리풀공원": (37.4930, 127.0010),
    "몽마르뜨공원": (37.4975, 127.0050), "서울광장": (37.5657, 126.9780), "서울대공원": (37.4270, 127.0170),
    "서울숲": (37.5444, 127.0374), "아차산": (37.5530, 127.1050), "양화한강공원": (37.5395, 126.9030),
    "어린이대공원": (37.5480, 127.0750), "여의도한강공원": (37.5285, 126.9330), "월드컵공원": (37.5650, 126.8970),
    "응봉산": (37.5525, 127.0285), "이촌한강공원": (37.5180, 126.9700), "잠실종합운동장": (37.5153, 127.0730),
    "잠실한강공원": (37.5180, 127.0820), "잠원한강공원": (37.5210, 127.0120), "청계산": (37.4480, 127.0560),
    "청와대": (37.5866, 126.9748), "북한산우이역": (37.6630, 127.0120), "보라매공원": (37.4930, 126.9200),
    "서대문독립공원": (37.5740, 126.9560), "안양천": (37.5250, 126.8800), "여의서로": (37.5310, 126.9200),
    "올림픽공원": (37.5206, 127.1214), "홍제폭포": (37.5800, 126.9350), "롯데월드": (37.5111, 127.0982),
    "코엑스": (37.5118, 127.0592), "타임스퀘어": (37.5170, 126.9033), "문래": (37.5160, 126.8950),
    "을지로": (37.5660, 126.9910), "성수": (37.5446, 127.0557), "이태원": (37.5345, 126.9946),
}

CAT = [("관광특구", "관광특구"), ("궁", "고궁·문화유산"), ("종묘", "고궁·문화유산"), ("유적", "고궁·문화유산"), ("보신각", "고궁·문화유산"),
       ("공원", "공원"), ("한강", "공원"), ("산", "공원"), ("숲", "공원"), ("천", "공원"), ("역", "인구밀집지역")]


def norm(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s or "")


def load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def items_of(js) -> list[dict]:
    """응답 어디에 있든 AREA_NM 을 가진 항목들을 찾는다 (필드 위치가 조금 달라도 동작하게)."""
    out = []
    if isinstance(js, dict):
        if "AREA_NM" in js:
            out.append(js)
        for v in js.values():
            out += items_of(v)
    elif isinstance(js, list):
        for v in js:
            out += items_of(v)
    return out


def fetch(key: str, area: str) -> dict | None:
    url = BASE.format(key=key, area=urllib.parse.quote(area))
    for attempt in range(3):
        try:
            r = S.get(url, timeout=20)
            js = r.json()
            it = items_of(js)
            if it:
                return it[0]
            res = json.dumps(js, ensure_ascii=False)[:160]
            if "INFO-200" in res or "해당하는 데이터가 없" in res:
                return None
            if "ERROR-" in res and attempt == 2:
                print("  응답:", res.replace(key, "***"))
            if "INFO-100" in res or "인증키" in res:
                raise SystemExit("서울시 인증키가 올바르지 않아요.")
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print("  실패:", str(e).replace(key, "***")[:120])
        time.sleep(1.5)
    return None


def num(v) -> int | None:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def coords_for(name: str, cache: dict):
    n = norm(name)
    if n in cache:
        return cache[n]
    best = None
    for k, ll in COORDS.items():
        kk = norm(k)
        if kk and (kk in n or n in kk) and (best is None or len(kk) > best[0]):
            best = (len(kk), ll)
    if best:
        cache[n] = list(best[1])
        return cache[n]
    # OpenStreetMap에서 한 번 찾기 (서울 안으로 제한, 1초 간격 예의)
    q = re.sub(r"(관광특구|일대|·)", " ", name).strip()
    try:
        time.sleep(1.1)
        r = S.get("https://nominatim.openstreetmap.org/search", timeout=20, params={
            "q": f"{q} 서울", "format": "json", "limit": 1, "countrycodes": "kr",
            "viewbox": "126.76,37.70,127.19,37.42", "bounded": 1})
        js = r.json()
        if js:
            cache[n] = [round(float(js[0]["lat"]), 5), round(float(js[0]["lon"]), 5)]
            return cache[n]
    except Exception as e:  # noqa: BLE001
        print("  위치 찾기 실패:", name, str(e)[:80])
    cache[n] = None
    return None


def main():
    key = os.environ.get("SEOUL_API_KEY", "").strip()
    sample = not key
    if sample:
        key = "sample"
        print("SEOUL_API_KEY가 없어 견본 키로 '광화문·덕수궁'만 확인해요.")
    OUT.mkdir(parents=True, exist_ok=True)
    places = load(OUT / "places.json", {"at": "", "codes": []})
    coords = load(OUT / "coords.json", {})
    today = dt.datetime.now(KST).date()

    if sample:
        codes = ["광화문·덕수궁"]
    else:
        if not places["codes"] or places.get("at", "") < (today - dt.timedelta(days=7)).isoformat():
            print("장소 목록 확인 중 (POI001~)…")
            found, miss = [], 0
            for i in range(1, 200):
                cd = f"POI{i:03d}"
                it = fetch(key, cd)
                if it:
                    found.append(cd); miss = 0
                else:
                    miss += 1
                    if miss >= 15 and i > 120:
                        break
            if found:
                places = {"at": today.isoformat(), "codes": found}
                (OUT / "places.json").write_text(json.dumps(places, ensure_ascii=False))
            print(f"장소 {len(found)}곳")
        codes = places["codes"]

    rows = []
    for cd in codes:
        it = fetch(key, cd)
        if not it:
            continue
        name = it.get("AREA_NM", "")
        ll = coords_for(name, coords)
        fc = []
        for f in it.get("FCST_PPLTN") or []:
            if isinstance(f, dict) and f.get("FCST_TIME"):
                fc.append([f.get("FCST_TIME", "")[-5:], f.get("FCST_CONGEST_LVL", ""), num(f.get("FCST_PPLTN_MIN")), num(f.get("FCST_PPLTN_MAX"))])
        cat = ("관광특구" if "관광특구" in name else "인구밀집지역" if re.search(r"역($|[·\s(])", name)
               else next((c for k, c in CAT if k in name), "발달상권"))
        rows.append({
            "cd": it.get("AREA_CD", cd), "name": name, "cat": cat,
            "lat": ll[0] if ll else None, "lng": ll[1] if ll else None,
            "lvl": it.get("AREA_CONGEST_LVL", ""), "msg": (it.get("AREA_CONGEST_MSG") or "")[:140],
            "min": num(it.get("AREA_PPLTN_MIN")), "max": num(it.get("AREA_PPLTN_MAX")),
            "time": it.get("PPLTN_TIME", ""), "fc": fc[:6],
        })
        time.sleep(0.15)
    (OUT / "coords.json").write_text(json.dumps(coords, ensure_ascii=False, separators=(",", ":")))
    if not rows:
        print("받은 장소가 없어요. 이전 자료를 그대로 둬요.")
        return
    data = {"at": dt.datetime.now(KST).isoformat(timespec="minutes"), "sample": sample, "places": rows}
    (OUT / "seoul.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    lv = {}
    for r in rows:
        lv[r["lvl"]] = lv.get(r["lvl"], 0) + 1
    print(f"인파지도: {len(rows)}곳 · 위치 없음 {sum(1 for r in rows if r['lat'] is None)} · {lv}")
    if sample:
        print("견본 응답:", json.dumps(rows[0], ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
# 2026-10-31T03:00:13Z 키 등록 후 실행
