"""오디(관광지 오디오 가이드) API 응답 확인용 탐색 스크립트. 수집 데이터는 만들지 않고 결과만 로그에 찍는다."""
import os, urllib.parse, urllib.request

ODII = "https://apis.data.go.kr/B551011/Odii"
OPS = ["storyBasedList", "storySearchList", "storyLocationBasedList"]
VARIANTS = [
    {"langCode": "ko"},
    {"langCode": "ko", "areaCode": "11"},
    {"langCode": "ko", "areaCode": "1"},
    {"langCode": "ko", "areaCode": "11", "sigunguCode": "1"},
    {"langCode": "ko", "mapX": "126.9770", "mapY": "37.5759", "radius": "2000"},
    {"langCode": "ko", "keyword": "경복궁"},
    {"langCode": "ko", "contentId": "126508"},
]

def run(op, key, extra):
    q = {"serviceKey": key, "MobileOS": "ETC", "MobileApp": "eodigallae", "_type": "json",
         "numOfRows": "2", "pageNo": "1", **extra}
    url = f"{ODII}/{op}?{urllib.parse.urlencode(q)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body, status = r.read().decode("utf-8", "replace"), r.status
    except urllib.error.HTTPError as e:
        body, status = e.read().decode("utf-8", "replace"), e.code
    except Exception as e:
        body, status = f"연결 실패 {type(e).__name__}", 0
    if "NO_OPENAPI_SERVICE" in body:
        return
    print(f"[ODII] {op} {extra}: HTTP {status} body={body[:900]!r}")

def main():
    key = os.environ.get("ODII_KEY", "").strip()
    if not key:
        print("ODII_KEY가 없어요. 저장소 Secrets에 ODII_KEY를 등록해 주세요.")
        return
    for op in OPS:
        for v in VARIANTS:
            run(op, key, v)

if __name__ == "__main__":
    main()
