#!/usr/bin/env python3
"""전국 주간 핫플 랭킹 (매주 월요일 새벽).

- 유튜브 이번 주 Top 10: 지난 7일 올라온 국내 여행 영상(검색 10회, 약 1,010 unit)에서
  장소 이름 + 도시 이름이 함께 나온 횟수와 조회수로 점수.
- 숨은 핫플 Top 10: 관광공사 목록에는 없고 카카오맵에서 찾은 카페·골목·전시 중 영상에 많이 나온 곳.
  (카카오는 인기 지표를 주지 않으므로 '발견'에만 쓰고, 순위는 유튜브로 매긴다)
- 꾸준한 인기 Top 10: 도시별로 모아 둔 최근 6개월 유튜브 점수.
- 급상승 Top 10: 이번 주 언급이 6개월 평균보다 크게 늘어난 곳.
지난주 파일과 비교해 순위 변화(▲▼, NEW)를 붙인다. 카카오 좌표·주소는 저장하지 않는다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buzz  # noqa: E402
import collect  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEEK_DIR = DATA / "weekly"

QUERIES = ["국내여행", "국내 여행 브이로그", "가볼만한곳", "요즘 핫플", "주말 나들이", "당일치기 여행",
           "데이트 코스", "카페 투어", "1박2일 여행", "여행 추천 국내"]

KST = dt.timezone(dt.timedelta(hours=9))


def week_label(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def weekly_pool(yt: buzz.YouTube, days: int = 7) -> list[dict]:
    after = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids: list[str] = []
    for q in QUERIES:
        js = yt._get(buzz.YT_SEARCH, 100, part="id", q=q, type="video", maxResults=50, regionCode="KR",
                     relevanceLanguage="ko", publishedAfter=after, order="viewCount", safeSearch="moderate")
        for it in js.get("items", []):
            vid = it.get("id", {}).get("videoId")
            if vid and vid not in ids:
                ids.append(vid)
    pool = []
    for i in range(0, len(ids), 50):
        js = yt._get(buzz.YT_VIDEOS, 1, part="snippet,statistics", id=",".join(ids[i:i + 50]), maxResults=50)
        for v in js.get("items", []):
            sn, st = v.get("snippet", {}), v.get("statistics", {})
            th = sn.get("thumbnails", {})
            pool.append({
                "id": v["id"], "title": sn.get("title", "")[:120], "channel": sn.get("channelTitle", "")[:40],
                "published": sn.get("publishedAt", "")[:10], "views": int(st.get("viewCount", 0) or 0),
                "thumb": (th.get("high") or th.get("medium") or th.get("default") or {}).get("url", ""),
                "text": " ".join([sn.get("title", ""), sn.get("description", "")[:3000], " ".join(sn.get("tags", [])[:30])])[:3500],
            })
    return pool


def mentions_city(v: dict, city: dict) -> bool:
    base = buzz.city_base(city["name"])
    return (len(base) >= 2 and base in v["text"]) or city["name"] in v["text"]


PROV_SHORT = {"경상남도": "경남", "경상북도": "경북", "전라남도": "전남", "충청남도": "충남", "충청북도": "충북",
              "전북특별자치도": "전북", "강원특별자치도": "강원", "제주특별자치도": "제주", "경기도": "경기"}


def city_of_address(addr: str, cities: list[dict]) -> dict | None:
    """카카오 주소 문자열에서 우리 도시 목록의 시·군을 찾는다 (주소 자체는 저장하지 않음)."""
    for c in sorted(cities, key=lambda c: -len(c["name"])):
        if c["province"] == c["name"]:
            continue
        prov = c["province"]
        if c["name"] in addr and (prov in addr or PROV_SHORT.get(prov, prov[:2]) in addr):
            return c
    for c in cities:   # 특별·광역시
        if c["province"] == c["name"] and addr.startswith((c["name"], buzz.city_base(c["name"]))):
            return c
    return None


def entry_of(p: dict, city: dict, score: dict, kind: str) -> dict:
    v = (p.get("videos") or [{}])[0]
    return {
        "name": p["name"], "city": city["name"], "province": city["province"], "cityId": city["id"],
        "spotId": p.get("id"), "kakao": p.get("kakao"), "cat": p.get("cat") or "", "kind": kind,
        "n": score["n"], "views": score["views"], "score": score["score"],
        "thumb": v.get("thumb") or p.get("thumb") or "", "image": p.get("image") or "",
        "video": {k: v.get(k) for k in ("id", "title", "channel", "views")} if v else None,
    }


def main():
    yt_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    kakao_key = os.environ.get("KAKAO_REST_KEY", "").strip()
    if not yt_key:
        sys.exit("YOUTUBE_API_KEY가 필요합니다.")
    today = dt.datetime.now(KST).date()
    label = week_label(today)
    index = collect.load_json(DATA / "cities.json", {"cities": []})
    cities = [c for c in index["cities"]]
    with_data = [c for c in cities if c.get("hasData")]

    yt = buzz.YouTube(collect.SESSION, yt_key, int(os.environ.get("WEEKLY_YT_UNITS", "1100")))
    pool = weekly_pool(yt)
    print(f"이번 주 영상 {len(pool)}편")

    # 도시별 저장된 장소 + 이번 주 영상으로 점수
    weekly, steady = [], []
    for c in with_data:
        d = collect.load_json(DATA / "cities" / f"{c['id']}.json", None)
        if not d:
            continue
        for s in d["spots"]:
            if s.get("yt"):
                steady.append(entry_of(s, c, s["yt"], "kakao" if s.get("type") == "kakao" else "spot"))
        sub = [v for v in pool if mentions_city(v, c)]
        if not sub:
            continue
        places = [dict(s, videos=[]) for s in d["spots"]]
        for p in places:
            p.pop("yt", None)
        buzz.score_places(places, sub, c)
        for p in places:
            if p.get("yt"):
                e = entry_of(p, c, p["yt"], "kakao" if p.get("type") == "kakao" else "spot")
                base = next((s.get("yt") for s in d["spots"] if s["id"] == p["id"]), None)
                e["base_n"] = base["n"] if base else 0
                weekly.append(e)

    # 아직 수집 안 된 도시까지: 영상 타임라인 이름 → 카카오로 확인 (이름·ID·도시만 저장)
    if kakao_key:
        kk = buzz.Kakao(collect.SESSION, kakao_key, max_calls=60)
        known = {(e["city"], buzz.norm(e["name"])) for e in weekly}
        for name, nvid, _ in buzz.extract_names(pool, {"name": "", "province": ""})[:40]:
            try:
                docs = kk.search(name, None, None)
            except Exception as e:  # noqa: BLE001
                print("카카오 중단:", e)
                break
            for doc in docs[:5]:
                if doc.get("category_group_code") not in buzz.KAKAO_CATS:
                    continue
                if not (buzz.norm(name) in buzz.norm(doc["place_name"]) or buzz.norm(doc["place_name"]) in buzz.norm(name)):
                    continue
                c = city_of_address(doc.get("address_name") or "", cities)
                if not c or (c["name"], buzz.norm(doc["place_name"])) in known:
                    break
                p = {"id": "k" + doc["id"], "type": "kakao", "name": doc["place_name"], "kakao": doc["id"],
                     "cat": buzz.KAKAO_CATS[doc["category_group_code"]], "videos": []}
                sub = [v for v in pool if mentions_city(v, c)] or pool
                buzz.score_places([p], sub, c)
                if p.get("yt"):
                    e = entry_of(p, c, p["yt"], "kakao")
                    e["base_n"] = 0
                    weekly.append(e)
                    known.add((c["name"], buzz.norm(p["name"])))
                break

    def top(items, key, n=10):
        out, seen = [], set()
        for e in sorted(items, key=key):
            k = (e["city"], buzz.norm(e["name"]))
            if k in seen:
                continue
            seen.add(k)
            out.append(e)
            if len(out) >= n:
                break
        return out

    # 급상승은 6개월 기준치가 있는 도시(유튜브 점수를 이미 매긴 도시)만 비교한다
    has_base = {e["city"] for e in steady}
    rising = [dict(e, ratio=round(e["n"] / (e["base_n"] / 26 + 0.5), 1)) for e in weekly
              if e["n"] >= 2 and e["city"] in has_base]
    result = {
        "week": label, "updatedAt": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "videos": len(pool), "citiesWithData": len(with_data),
        "lists": {
            "youtube": top(weekly, lambda e: -e["score"]),
            "hidden": top([e for e in steady if e["kind"] == "kakao"]
                          + [e for e in weekly if e["kind"] == "kakao"], lambda e: -e["score"]),
            "steady": top(steady, lambda e: -e["score"]),
            "rising": top([e for e in rising if e["ratio"] >= 2], lambda e: -e["ratio"]),
        },
    }

    # 지난주와 비교
    prev_files = sorted(p for p in WEEK_DIR.glob("*.json") if p.stem < label) if WEEK_DIR.exists() else []
    prev = collect.load_json(prev_files[-1], None) if prev_files else None
    for key, items in result["lists"].items():
        old = {(e["city"], e["name"]): i for i, e in enumerate((prev or {}).get("lists", {}).get(key, []), 1)}
        for i, e in enumerate(items, 1):
            o = old.get((e["city"], e["name"]))
            e["change"] = "new" if prev and o is None else (o - i if o else None)

    WEEK_DIR.mkdir(parents=True, exist_ok=True)
    collect.save_json(WEEK_DIR / f"{label}.json", result)
    collect.save_json(DATA / "weekly.json", result)
    for k, v in result["lists"].items():
        print(k, [f"{e['city']} {e['name']}" for e in v])
    print("남은 유튜브 unit", yt.units)


if __name__ == "__main__":
    main()
