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
KEY = os.environ.get("SEOUL_API_KEY", "").strip()
LOOP_MIN = float(os.environ.get("SUBWAY_LOOP_MIN", "13"))
EVERY = float(os.environ.get("SUBWAY_EVERY_SEC", "30"))
URL = "http://swopenapi.seoul.go.kr/api/subway/{key}/json/realtimePosition/0/200/{line}"
S = requests.Session()
S.headers["User-Agent"] = "eodigallae/1.0 (github.com/lloydknam/eodigallae)"


def clean(text: object) -> str:
    """오류 문구에 인증키가 섞여 나가지 않도록 가린다."""
    t = str(text)
    return t.replace(KEY, "***").replace(urllib.parse.quote(KEY, safe=""), "***") if KEY else t


def fetch_line(n: int) -> tuple[list[dict], dict]:
    info: dict = {"line": n}
    try:
        r = S.get(URL.format(key=KEY, line=urllib.parse.quote(f"{n}호선")), timeout=15)
        info["http"] = r.status_code
        j = r.json()
    except Exception as e:  # noqa: BLE001
        info["error"] = clean(e)[:200]
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


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def main() -> int:
    if not KEY:
        print("SEOUL_API_KEY가 없어요.")
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
        git(work, "add", "-A")
        msg = f"subway {time.strftime('%H:%M:%S', time.gmtime())}Z {len(data['trains'])}대"
        if first:
            git(work, "commit", "-q", "-m", msg)
        else:
            git(work, "commit", "-q", "--amend", "-m", msg)
        p = git(work, "push", "-q", "-f", "origin", "HEAD:refs/heads/live-data", check=False)
        print(f"[{n}] {msg} push={'ok' if p.returncode == 0 else clean(p.stderr)[:200]}", flush=True)
        first = False
        n += 1
        if time.time() + EVERY >= deadline:
            break
        time.sleep(max(1.0, EVERY - (time.time() - started)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
