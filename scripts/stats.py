#!/usr/bin/env python3
"""방문 통계 보관: 무료 카운터(Abacus)의 날짜별 숫자를 data/stats.json 에 옮겨 적는다.
카운터는 6개월 안 쓰면 사라지므로 매일 최근 7일치를 가져와 영구 보관한다."""
import datetime as dt
import json
from pathlib import Path

import requests

BASE = "https://abacus.jasoncameron.dev/get/eodigallae.lloydknam"
OUT = Path(__file__).resolve().parent.parent / "data" / "stats.json"
KST = dt.timezone(dt.timedelta(hours=9))


def get(key: str) -> int:
    try:
        r = requests.get(f"{BASE}/{key}", timeout=15)
        return int(r.json().get("value") or 0) if r.ok else 0
    except Exception:
        return 0


def main():
    data = json.loads(OUT.read_text()) if OUT.exists() else {"days": {}}
    today = dt.datetime.now(KST).date()
    for back in range(7):
        d = (today - dt.timedelta(days=back)).strftime("%Y%m%d")
        v, p = get(f"v-{d}"), get(f"p-{d}")
        old = data["days"].get(d, [0, 0])
        if v or p or d in data["days"]:
            data["days"][d] = [max(v, old[0]), max(p, old[1])]
    data["days"] = dict(sorted(data["days"].items()))
    data["at"] = dt.datetime.now(KST).isoformat(timespec="minutes")
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print("방문 통계:", list(data["days"].items())[-3:])


if __name__ == "__main__":
    main()
