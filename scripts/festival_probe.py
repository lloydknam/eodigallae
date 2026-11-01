"""축제공연행사정보(searchFestival2) 응답 확인용. 수집 데이터는 만들지 않는다."""
import json, os, urllib.parse, urllib.request
from datetime import date, timedelta

BASE = "https://apis.data.go.kr/B551011/KorService2"

def main():
    key = os.environ.get("TOURAPI_KEY", "").strip()
    if not key:
        print("TOURAPI_KEY가 없어요."); return
    today = date.today().strftime("%Y%m%d")
    end = (date.today() + timedelta(days=120)).strftime("%Y%m%d")
    q = {"serviceKey": key, "MobileOS": "ETC", "MobileApp": "eodigallae", "_type": "json",
         "numOfRows": "5", "pageNo": "1", "arrange": "A",
         "eventStartDate": today, "eventEndDate": end}
    url = f"{BASE}/searchFestival2?{urllib.parse.urlencode(q)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
    js = json.loads(body)
    b = js.get("response", {}).get("body", {})
    print("total:", b.get("totalCount"))
    items = b.get("items", {}).get("item")
    items = items if isinstance(items, list) else [items] if items else []
    for it in items[:5]:
        print("FIELDS:", sorted(it.keys()))
        print(json.dumps(it, ensure_ascii=False)[:800])

if __name__ == "__main__":
    main()
