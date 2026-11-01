"""전국문화축제표준데이터(15013104) 응답 확인용. 수집 데이터는 만들지 않는다."""
import json, os, urllib.parse, urllib.request

CANDIDATES = [
    "https://api.data.go.kr/openapi/tn_pubr_public_cltur_fstvl_api",
    "https://api.data.go.kr/openapi/tn_pubr_public_festival_api",
]

def try_url(base, key):
    q = {"serviceKey": key, "pageNo": "1", "numOfRows": "3", "type": "json"}
    url = f"{base}?{urllib.parse.urlencode(q)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body, status = r.read().decode("utf-8", "replace"), r.status
    except urllib.error.HTTPError as e:
        body, status = e.read().decode("utf-8", "replace"), e.code
    except Exception as e:
        print(f"[{base}] 연결 실패 {type(e).__name__}"); return False
    print(f"[{base}] status {status}")
    try:
        js = json.loads(body)
        print(json.dumps(js, ensure_ascii=False)[:1800])
        hdr = js.get("header") or js.get("response", {}).get("header", {})
        return str(hdr.get("resultCode")) in ("00", "0000")
    except Exception:
        print("JSON 아님:", body[:500]); return False

def main():
    key = os.environ.get("FESTIVAL_STD_KEY", "").strip()
    if not key:
        print("FESTIVAL_STD_KEY가 없어요."); return
    for base in CANDIDATES:
        if try_url(base, key):
            print("OK:", base)
            return

if __name__ == "__main__":
    main()
