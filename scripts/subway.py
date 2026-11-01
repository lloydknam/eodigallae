#!/usr/bin/env python3
"""열차지도(수도권 지하철): 서울시 실시간 열차 위치(1~9호선)를 모아 live-data 브랜치의 subway.json 으로 올린다.

- 서울시 서버가 https를 지원하지 않아 앱이 직접 부를 수 없으므로 GitHub Actions가 대신 받아 둔다.
- 한 번 실행하면 SUBWAY_LOOP_MIN분 동안 SUBWAY_EVERY_SEC초마다 받아서 올린다(기본 13분, 30초).
- 결과는 `live-data` 브랜치에 커밋 한 개로 계속 덮어쓴다(기록이 쌓이지 않고, 사이트 재배포도 일어나지 않는다).
- probe.json 에는 응답 형식 확인용 요약(호선별 상태·필드 이름·첫 열차 한 건)을 남긴다. 인증키는 어디에도 쓰지 않는다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
# 실시간 지하철은 별도로 발급받은 인증키가 필요하다. SEOUL_SUBWAY_KEY 가 있으면 그것을, 없으면 SEOUL_API_KEY 를 쓴다.
KEY = (os.environ.get("SEOUL_SUBWAY_KEY") or os.environ.get("SEOUL_API_KEY") or "").strip()
LOOP_MIN = float(os.environ.get("SUBWAY_LOOP_MIN", "13"))
EVERY = float(os.environ.get("SUBWAY_EVERY_SEC", "30"))
URL = "http://swopenapi.seoul.go.kr/api/subway/{key}/json/realtimePosition/0/{end}/{line}"
S = requests.Session()
S.headers["User-Agent"] = "eodigallae/1.0 (github.com/lloydknam/eodigallae)"


def clean(text: object) -> str:
    """오류 문구에 인증키가 섞여 나가지 않도록 가린다."""
    t = str(text)
    return t.replace(KEY, "***").replace(urllib.parse.quote(KEY, safe=""), "***") if KEY else t


def fetch_line(n: int, key: str | None = None, end: int = 200) -> tuple[list[dict], dict]:
    key = key or KEY
    info: dict = {"line": n}
    j = None
    for attempt in range(3):  # 서울시 서버 접속이 가끔 시간 초과로 끊기므로 세 번까지 다시 시도한다
        try:
            r = S.get(URL.format(key=key, end=end, line=urllib.parse.quote(f"{n}호선")), timeout=(8, 12))
            info["http"] = r.status_code
            j = r.json()
            info.pop("error", None)
            break
        except Exception as e:  # noqa: BLE001
            info["error"] = clean(e)[:160]
            info["attempts"] = attempt + 1
            time.sleep(2)
    if j is None:
        return [], info
    err = j.get("errorMessage") or {}
    if err:
        info["status"] = err.get("status")
        info["code"] = err.get("code")
        info["message"] = clean(err.get("message"))[:200]
    if "code" in j and "message" in j:  # 인증 오류 등 최상위 오류 형식
        info["code"] = j.get("code")
        info["message"] = clean(j.get("message"))[:200]
    rows = j.get("realtimePositionList")
    if not isinstance(rows, list):
        return [], info
    info["count"] = len(rows)
    if rows:
        info["fields"] = sorted(rows[0].keys())
        info["first"] = {k: clean(v) for k, v in rows[0].items()}
        info["updnLine_values"] = sorted({str(x.get("updnLine")) for x in rows})
        info["trainSttus_values"] = sorted({str(x.get("trainSttus")) for x in rows})
        info["directAt_values"] = sorted({str(x.get("directAt")) for x in rows})
    out = []
    for t in rows:
        try:
            out.append({"l": n, "t": t.get("trainNo"), "s": t.get("statnNm"), "d": t.get("statnTnm"),
                        "u": int(t.get("updnLine")), "st": int(t.get("trainSttus")), "x": int(t.get("directAt") or 0)})
        except (TypeError, ValueError):
            continue
    return out, info


def snapshot() -> tuple[dict, dict]:
    with ThreadPoolExecutor(max_workers=9) as ex:
        res = list(ex.map(fetch_line, range(1, 10)))
    trains = [t for rows, _ in res for t in rows]
    ok = sum(1 for _, i in res if i.get("count") is not None)
    now = int(time.time() * 1000)
    data = {"at": now, "lines": ok, "trains": trains}
    probe = {"at": now, "ok_lines": ok, "total": len(trains), "per_line": [i for _, i in res]}
    return data, probe


def sample_probe() -> dict:
    """서울시 견본 키('sample')로 응답 형식만 확인한다. 이 데이터는 앱에 쓰지 않는다."""
    with ThreadPoolExecutor(max_workers=9) as ex:
        res = list(ex.map(lambda n: fetch_line(n, "sample", 5), range(1, 10)))
    # 요청 건수(끝 위치)를 바꿔 가며 어디서 오류가 나는지 확인한다(2호선만, 두 키로).
    ranges = []
    for who, k in (("sample", "sample"), ("mine", KEY)):
        for end in (5, 50, 100, 200, 500, 1000):
            _, i = fetch_line(2, k, end)
            ranges.append({"key": who, "end": end, "code": i.get("code"), "count": i.get("count"), "message": (i.get("message") or "")[:60]})
    return {"note": "견본 키 응답(형식 확인용)", "per_line": [i for _, i in res], "ranges": ranges}


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def main() -> int:
    if not KEY:
        print("SEOUL_SUBWAY_KEY(또는 SEOUL_API_KEY)가 없어요.")
        return 1
    # 체크아웃에 저장된 인증 설정을 빌려 쓴다(액세스 토큰을 직접 다루지 않는다).
    header = git(ROOT, "config", "--get", "http.https://github.com/.extraheader", check=False).stdout.strip()
    remote = git(ROOT, "remote", "get-url", "origin").stdout.strip()
    work = Path(tempfile.mkdtemp(prefix="subway-"))
    git(work, "init", "-q")
    git(work, "config", "user.name", "github-actions[bot]")
    git(work, "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git(work, "remote", "add", "origin", remote)
    if header:
        git(work, "config", "http.https://github.com/.extraheader", header)
    git(work, "checkout", "-q", "-b", "live-data")
    first = True
    deadline = time.time() + LOOP_MIN * 60
    n = 0
    while True:
        started = time.time()
        data, probe = snapshot()
        (work / "subway.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if first or n % 20 == 0:
            (work / "probe.json").write_text(json.dumps(probe, ensure_ascii=False, indent=1), encoding="utf-8")
        if first and data["lines"] == 0:
            (work / "probe_sample.json").write_text(json.dumps(sample_probe(), ensure_ascii=False, indent=1), encoding="utf-8")
        git(work, "add", "-A")
        msg = f"subway {time.strftime('%H:%M:%S', time.gmtime())}Z {len(data['trains'])}대"
        if first:
            git(work, "commit", "-q", "-m", msg)
        else:
            git(work, "commit", "-q", "--amend", "-m", msg)
        p = git(work, "push", "-q", "-f", "origin", "HEAD:refs/heads/live-data", check=False)
        print(f"[{n}] {msg} push={'ok' if p.returncode == 0 else clean(p.stderr)[:200]}", flush=True)
        if first and data["lines"] == 0 and all("code" in i for i in probe["per_line"]):
            # 서울시가 응답은 했는데 거절한 경우(키가 실시간 서비스용이 아님 등): 13분 내내 빈 데이터를 올리지 않고 다음 예약 실행에 맡긴다.
            # (접속 시간 초과처럼 응답 자체가 없던 경우는 계속 다시 시도한다)
            print("열차 위치를 한 노선도 받지 못했어요. probe.json 을 확인해 주세요.", flush=True)
            break
        first = False
        n += 1
        if time.time() + EVERY >= deadline:
            break
        time.sleep(max(1.0, EVERY - (time.time() - started)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
