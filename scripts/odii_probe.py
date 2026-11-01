"""오디(관광지 오디오 가이드) API 응답 확인용 탐색 스크립트. 수집 데이터는 만들지 않고 결과만 로그에 찍는다."""
import json, os, urllib.parse, urllib.request

ODII = "https://apis.data.go.kr/B551011/Odii"

def run(op, key, extra):
    q = {"serviceKey": key, "MobileOS": "ETC", "MobileApp": "eodigallae", "_type": "json",
         "numOfRows": "3", "pageNo": "1", "langCode": "ko", **extra}
    url = f"{ODII}/{op}?{urllib.parse.urlencode(q)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body, status = r.read().decode("utf-8", "replace"), r.status
    except urllib.error.HTTPError as e:
        body, status = e.read().decode("utf-8", "replace"), e.code
    except Exception as e:
        print(f"[ODII] {op} {extra}: 연결 실패 {type(e).__name__}")
        return
    try:
        js = json.loads(body)
        items = js["response"]["body"]["items"]["item"]
    except Exception:
        print(f"[ODII] {op} {extra}: HTTP {status} body={body[:400]!r}")
        return
    for item in items:
        print(f"[ODII] {op} {extra} FIELDS: {sorted(item.keys())}")
        print(json.dumps(item, ensure_ascii=False)[:2200])

def main():
    key = os.environ.get("ODII_KEY", "").strip()
    if not key:
        print("ODII_KEY가 없어요. 저장소 Secrets에 ODII_KEY를 등록해 주세요.")
        return
    run("storySearchList", key, {"keyword": "경복궁"})
    run("storyLocationBasedList", key, {"mapX": "126.9770", "mapY": "37.5759", "radius": "3000"})
    run("storyBasedList", key, {})

if __name__ == "__main__":
    main()
