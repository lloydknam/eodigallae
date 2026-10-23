#!/usr/bin/env python3
"""이번 주말 붐빔 예보: 한국관광공사 '관광지 집중률 방문자 추이 예측 정보'(KT 통신 데이터 기반, 30일 예측).

- 시군구 단위로 관광지별 날짜별 집중률(0~100, 그 관광지의 가장 붐비는 때를 100으로 둔 상대값)을 받는다.
- 우리 관광지 이름과 맞춰 앞으로 14일 값만 data/crowd/<도시id>.json 에 저장한다(도시별 7일마다 갱신).
- 이 서비스의 하루 호출 한도(개발계정 1,000)는 관광정보 서비스와 따로라 별도로 센다.
- 활용신청 전이면 첫 호출에서 오류가 나므로 조용히 끝낸다.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402

CROWD_BASE = "https://apis.data.go.kr/B551011/TatsCnctrRateService"
DATA = collect.DATA
OUT = DATA / "crowd"
KST = dt.timezone(dt.timedelta(hours=9))


def pick(item: dict, *needles: str) -> str:
    """응답 필드 이름이 문서와 조금 달라도 찾을 수 있게 소문자 부분 일치로 고른다."""
    for k, v in item.items():
        lk = k.lower()
        if any(n in lk for n in needles):
            return v
    return ""


def fetch_code(api: collect.TourAPI, code: str, max_pages: int = 10) -> list[dict]:
    rows = []
    for page in range(1, max_pages + 1):
        items = api.get("tatsCnctrRatedList", _base=CROWD_BASE, areaCd=code[:2], signguCd=code,
                        numOfRows=1000, pageNo=page)
        rows.extend(items)
        if len(items) < 1000:
            break
    return rows


def norm(s: str) -> str:
    return collect.norm_name(s)


def main():
    key = os.environ.get("TOURAPI_KEY", "").strip()
    if not key:
        sys.exit("TOURAPI_KEY가 필요합니다.")
    max_calls = int(os.environ.get("CROWD_MAX_CALLS", "900"))
    api = collect.TourAPI(key, max_calls)
    index = collect.load_json(DATA / "cities.json", {"cities": []})
    OUT.mkdir(parents=True, exist_ok=True)
    today = dt.datetime.now(KST).date()
    stale_before = (today - dt.timedelta(days=7)).isoformat()

    def age(c):
        cur = collect.load_json(OUT / f"{c['id']}.json", None)
        return (cur or {}).get("at", "")

    targets = [c for c in index["cities"] if c.get("hasData") and c.get("ldong")]
    def empty(c):
        cur = collect.load_json(OUT / f"{c['id']}.json", None)
        return bool(cur) and not cur.get("spots") and cur.get("at", "") < today.isoformat()

    targets = [c for c in targets if age(c) < stale_before or empty(c)]
    targets.sort(key=age)
    done = 0
    for c in targets:
        d = collect.load_json(DATA / "cities" / f"{c['id']}.json", None)
        if not d:
            continue
        try:
            rows = []
            for code in c["ldong"]:
                rows += fetch_code(api, code)
            if not rows and any(x.startswith("12") for x in c["ldong"]):
                # 전남광주통합특별시 새 코드(12xxx)로 예측 자료가 없으면 옛 코드로
                old = [v for k, v in collect.OLD_SIGUNGU.items() if v.startswith("29")] if c["name"] == "광주" \
                    else [collect.OLD_SIGUNGU[c["name"]]] if c["name"] in collect.OLD_SIGUNGU else []
                for code in old:
                    rows += fetch_code(api, code)
        except collect.QuotaError as e:
            print("한도:", e)
            break
        except RuntimeError as e:
            msg = collect.redact(e)
            print(f"{c['name']}: 오류 {msg}")
            if any(w in msg for w in ("SERVICE_KEY", "인증", "NOT_REGISTERED", "ACCESS DENIED", "등록되지")):
                print("관광지 집중률 서비스 활용신청이 아직 안 된 것 같아요. 신청 뒤 다음 실행부터 수집해요.")
                break
            continue
        # 관광지별 날짜별 값
        series: dict[str, dict[str, int]] = {}
        for r in rows:
            name = pick(r, "tatsnm", "atsnm") or ""
            ymd = str(pick(r, "ymd") or "")
            rate = pick(r, "rate")
            if not name or not re.fullmatch(r"\d{8}", ymd):
                continue
            try:
                series.setdefault(norm(name), {})[ymd] = int(round(float(rate)))
            except (TypeError, ValueError):
                continue
        # 우리 관광지와 이름 맞추기 (같거나, 한쪽이 다른 쪽을 포함)
        spots_out = {}
        keys = list(series)
        for s in d["spots"]:
            n = norm(s["name"])
            if not n:
                continue
            k = n if n in series else next((k for k in keys if len(min(k, n, key=len)) >= 3 and (k in n or n in k)), None)
            if not k:
                continue
            days = sorted(series[k].items())
            days = [(ymd, v) for ymd, v in days if ymd >= today.strftime("%Y%m%d")][:14]
            if days:
                spots_out[s["id"]] = days
        collect.save_json(OUT / f"{c['id']}.json", {"at": today.isoformat(), "spots": spots_out}, compact=True)
        print(f"{c['name']}: 예측 관광지 {len(series)}곳 중 {len(spots_out)}곳 연결 · 호출 {api.calls}")
        done += 1
    print(f"붐빔 예보 완료: 도시 {done}곳 · 호출 {api.calls}회")


if __name__ == "__main__":
    main()
