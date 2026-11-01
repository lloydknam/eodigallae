# 생활인구 월별 파일 내려받기 경로 찾기 (일회성 확인용)
import json, re, requests
from pathlib import Path
out = {}
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"
for tab in ["F", "S"]:
    url = f"https://data.seoul.go.kr/dataList/OA-14991/{tab}/1/datasetView.do"
    try:
        h = S.get(url, timeout=40).text
        out[tab + "_len"] = len(h)
        idx = [m.start() for m in re.finditer("2025(11|10|12)", h)][:6]
        out[tab + "_ctx"] = [h[max(0, i - 400): i + 200] for i in idx]
        out[tab + "_dl"] = sorted(set(re.findall(r"(?:downloadFile|fileDownload|nio_download|fn_\w*[Dd]own\w*)[^;\"']{0,160}", h)))[:40]
    except Exception as e:
        out[tab + "_err"] = str(e)[:200]
Path("data/history/probe_files.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
