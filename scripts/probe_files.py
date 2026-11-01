# 생활인구 월별 파일 내려받기 경로 찾기 (일회성 확인용)
import io, json, re, zipfile, requests
from pathlib import Path
out = {}
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"
h = S.get("https://data.seoul.go.kr/dataList/OA-14991/F/1/datasetView.do", timeout=40).text
i = h.find('name="frmFile"'); i = i if i >= 0 else h.find("frmFile")
out["form"] = h[max(0, i - 300): i + 900]
j = h.find("function downloadFile"); out["fn"] = h[j: j + 900]
Path("data/history/probe_files.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
