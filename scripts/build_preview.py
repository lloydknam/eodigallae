#!/usr/bin/env python3
"""index.html에서 미리보기용 본문만 뽑아 preview/index.html로 저장 (Claude 미리보기 페이지 게시용).
GitHub Pages 배포에는 필요 없다."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = (ROOT / "index.html").read_text(encoding="utf-8")
head = re.search(r"<head>(.*?)</head>", src, re.S).group(1)
body = re.search(r"<body>(.*?)</body>", src, re.S).group(1)
keep = [l for l in head.splitlines()
        if not re.search(r'charset|name="viewport"|manifest|rel="icon"|apple-touch|theme-color', l)]
out = "\n".join(keep).strip() + "\n" + body.strip() + "\n"
dst = ROOT / "preview" / "index.html"
dst.parent.mkdir(exist_ok=True)
dst.write_text(out, encoding="utf-8")
print(dst, len(out))
