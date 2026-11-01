#!/usr/bin/env python3
"""작년 이맘때 인파지도: 서울 생활인구(행정동, 1시간 단위, 통신 데이터 기반)로
작년 같은 요일(공휴일이면 작년 같은 공휴일) 08시 ~ 다음날 05시의 변화를 만든다.

- 서울시 실시간 121곳 데이터는 과거 기록이 공개되지 않아, 과거가 남는 '행정동 생활인구'를 쓴다.
- 결과: data/history/<작년날짜>.json, data/history/index.json (오늘·내일 → 작년 날짜)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "history"
KST = dt.timezone(dt.timedelta(hours=9))
API = "http://openapi.seoul.go.kr:8088/{key}/json/{svc}/{a}/{b}/{day}"
SERVICES = ["SPOP_LOCAL_RESD_DONG"]
HOURS = list(range(8, 24)) + list(range(0, 6))   # 08시 ~ 다음날 05시 (22시간)

# 공휴일(이름이 같으면 작년 같은 공휴일로 맞춘다)
HOLIDAYS = {
    "신정": ["2025-01-01", "2026-01-01", "2027-01-01"],
    "설날 연휴": ["2025-01-28", "2025-01-29", "2025-01-30", "2026-02-16", "2026-02-17", "2026-02-18", "2027-02-06", "2027-02-07", "2027-02-08"],
    "삼일절": ["2025-03-01", "2026-03-01", "2027-03-01"],
    "어린이날": ["2025-05-05", "2026-05-05", "2027-05-05"],
    "부처님오신날": ["2025-05-05", "2026-05-24", "2027-05-13"],
    "현충일": ["2025-06-06", "2026-06-06", "2027-06-06"],
    "광복절": ["2025-08-15", "2026-08-15", "2027-08-15"],
    "추석 연휴": ["2025-10-05", "2025-10-06", "2025-10-07", "2026-09-24", "2026-09-25", "2026-09-26", "2027-09-14", "2027-09-15", "2027-09-16"],
    "개천절": ["2025-10-03", "2026-10-03", "2027-10-03"],
    "한글날": ["2025-10-09", "2026-10-09", "2027-10-09"],
    "핼러윈": ["2025-10-31", "2026-10-31", "2027-10-31"],
    "크리스마스": ["2025-12-25", "2026-12-25", "2027-12-25"],
    "12월 31일": ["2025-12-31", "2026-12-31", "2027-12-31"],
}
DOW = "월화수목금토일"


def last_year(d: dt.date) -> tuple[dt.date, str]:
    s = d.isoformat()
    for name, days in HOLIDAYS.items():
        if s in days:
            mine = [x for x in days if x[:4] == s[:4]]
            prev = [x for x in days if x[:4] == str(d.year - 1)]
            if prev:
                k = min(mine.index(s), len(prev) - 1)
                p = dt.date.fromisoformat(prev[k])
                return p, f"작년 {name}"
    p = d - dt.timedelta(days=364)   # 52주 전 = 같은 요일
    return p, "작년 같은 요일"


def pick(row: dict, *needles: str):
    for k, v in row.items():
        if any(n in k.upper() for n in needles):
            return v
    return None


def rows_of(js) -> list[dict]:
    out = []
    if isinstance(js, dict):
        if any("TMZON" in k.upper() for k in js):
            out.append(js)
        for v in js.values():
            out += rows_of(v)
    elif isinstance(js, list):
        for v in js:
            out += rows_of(v)
    return out


def fetch_day(key: str, day: dt.date, diag: list) -> dict[str, dict[int, float]]:
    """{행정동코드: {시: 총생활인구}}"""
    ymd = day.strftime("%Y%m%d")
    for svc in SERVICES:
        got: dict[str, dict[int, float]] = {}
        a = 1
        while True:
            url = API.format(key=key, svc=svc, a=a, b=a + 999, day=ymd)
            try:
                js = requests.get(url, timeout=30).json()
            except Exception as e:  # noqa: BLE001
                diag.append(f"{svc} {ymd} {a}: {str(e).replace(key, '***')[:160]}")
                break
            rows = rows_of(js)
            if not rows:
                diag.append(f"{svc} {ymd} {a}: {json.dumps(js, ensure_ascii=False)[:300].replace(key, '***')}")
                break
            for r in rows:
                code = str(pick(r, "ADSTRD") or "")[:8]
                hr = pick(r, "TMZON")
                tot = pick(r, "TOT_LVPOP", "TOT")
                try:
                    got.setdefault(code, {})[int(hr)] = round(float(tot))
                except (TypeError, ValueError):
                    continue
            if len(rows) < 1000:
                break
            a += 1000
            time.sleep(0.3)
        if got:
            if not diag or "필드" not in diag[0]:
                diag.insert(0, f"필드 예시: {sorted(rows[0].keys()) if rows else []}")
            return got
    return {}


def build(key: str, today: dt.date, diag: list) -> dict | None:
    d0, why = last_year(today)
    fn = OUT / f"{d0.strftime('%Y%m%d')}.json"
    if fn.exists():
        return {"file": fn.name, "date": d0.isoformat(), "why": why}
    a = fetch_day(key, d0, diag)
    b = fetch_day(key, d0 + dt.timedelta(days=1), diag)
    if not a:
        diag.append(f"{d0} 자료 없음")
        return None
    dongs = json.loads((OUT / "dongs.json").read_text())["dongs"]
    vals = {}
    for code, *_ in dongs:
        row = [a.get(code, {}).get(h) for h in HOURS[:16]] + [b.get(code, {}).get(h) for h in HOURS[16:]]
        if sum(v is not None for v in row) >= 12:
            vals[code] = row
    if not vals:
        diag.append(f"{d0} 행정동 코드가 맞지 않음: 예시 {list(a)[:5]}")
        return None
    nxt = d0 + dt.timedelta(days=1)
    fn.write_text(json.dumps({
        "date": d0.isoformat(), "why": why, "dow": DOW[d0.weekday()], "nextDow": DOW[nxt.weekday()],
        "hours": HOURS, "values": vals, "src": "서울시 생활인구(행정동, 통신 데이터 기반 추정)",
    }, ensure_ascii=False, separators=(",", ":")))
    print(f"{today} → {d0} ({why}) 행정동 {len(vals)}곳")
    return {"file": fn.name, "date": d0.isoformat(), "why": why}


def main():
    key = os.environ.get("SEOUL_API_KEY", "").strip()
    if not key:
        sys.exit("SEOUL_API_KEY가 필요해요.")
    today = dt.datetime.now(KST).date()
    if os.environ.get("PROBE"):   # 자료가 있는 날짜 범위 확인용
        log = []
        for ymd in os.environ["PROBE"].split(","):
            url = API.format(key=key, svc=SERVICES[0], a=1, b=2, day=ymd)
            try:
                txt = requests.get(url, timeout=30).text.replace(key, "***")
            except Exception as e:  # noqa: BLE001
                txt = str(e).replace(key, "***")
            log.append(f"{ymd}: {txt[:260]}")
        (OUT / "probe.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
        print("\n".join(log))
        return
    idx_path = OUT / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    diag: list[str] = []
    for d in [today, today + dt.timedelta(days=1)]:
        r = build(key, d, diag)
        if r:
            idx[d.isoformat()] = r
    keep = (today - dt.timedelta(days=7)).isoformat()
    idx = {k: v for k, v in sorted(idx.items()) if k >= keep}
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=1))
    (OUT / "diag.json").write_text(json.dumps({"at": dt.datetime.now(KST).isoformat(timespec="minutes"), "log": diag[:20]}, ensure_ascii=False, indent=1))
    print("\n".join(diag[:10]))


if __name__ == "__main__":
    main()
