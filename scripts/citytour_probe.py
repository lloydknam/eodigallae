"""전국시티투어정보표준데이터 응답 확인용. 수집 데이터는 만들지 않는다."""
import json, os, urllib.parse, urllib.request

BASE = "https://api.data.go.kr/openapi/tn_pubr_public_city_tour_api"

def main():
    key = os.environ.get("CITYTOUR_KEY", "").strip()
    if not key:
        print("CITYTOUR_KEY가 없어요."); return
    q = {"serviceKey": key, "pageNo": "1", "numOfRows": "5", "type": "json"}
    url = f"{BASE}?{urllib.parse.urlencode(q)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body, status = r.read().decode("utf-8", "replace"), r.status
    except urllib.error.HTTPError as e:
        body, status = e.read().decode("utf-8", "replace"), e.code
    except Exception as e:
        print(f"연결 실패 {type(e).__name__}"); return
    print("status", status)
    try:
        js = json.loads(body)
        print(json.dumps(js, ensure_ascii=False)[:2500])
    except Exception:
        print("JSON 아님:", body[:1500])

if __name__ == "__main__":
    main()
