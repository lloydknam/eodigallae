"""오디(관광지 오디오 가이드) API 응답 확인용 탐색 스크립트. 수집 데이터는 만들지 않고 결과만 로그에 찍는다."""
import json, os, urllib.parse, urllib.request

ODII = "https://apis.data.go.kr/B551011/Odii"
ENG = "https://apis.data.go.kr/B551011/EngService2"
OPS_ODII = ["storyBasedList", "areaBasedList", "areaBasedList", "areaBasedList2", "locationBasedList", "locationBasedList2", "searchKeyword",
            "searchKeyword2", "detailCommon", "detailCommon2", "detailInfo", "detailIntro", "detailIntro2",
            "storyList", "storyDetail", "syncList", "syncList2", "storyBasedList", "areaCode", "categoryCode"]
OPS_ENG = ["areaBasedList2"]

def call(base, op, key, env_name):
    q = {"serviceKey": key, "MobileOS": "ETC", "MobileApp": "eodigallae", "_type": "json",
         "numOfRows": "2", "pageNo": "1", "arrange": "A", "areaCode": "1", "contentTypeId": "12",
         "keyword": "경복궁", "mapX": "126.9770", "mapY": "37.5759", "radius": "2000", "contentId": "126508"}
    url = f"{base}/{op}?{urllib.parse.urlencode(q)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        body, status = e.read().decode("utf-8", "replace"), e.code
    except Exception as e:
        print(f"[{env_name}] {op}: 연결 실패 {type(e).__name__}"); return
    try:
        js = json.loads(body)
        hdr = js.get("response", {}).get("header", {})
        items = js.get("response", {}).get("body", {}).get("items", {})
        cnt = js.get("response", {}).get("body", {}).get("totalCount")
        first = items.get("item") if isinstance(items, dict) else None
        if isinstance(first, list) and first:
            fields = sorted(first[0].keys())
        elif isinstance(first, dict):
            fields = sorted(first.keys())
        else:
            fields = []
        print(f"[{env_name}] {op}: HTTP {status} code={hdr.get('resultCode')} msg={hdr.get('resultMsg')} total={cnt} fields={fields} body={body[:260]!r}")
        if fields:
            print("   sample:", json.dumps(first if isinstance(first, dict) else first[0], ensure_ascii=False)[:600])
    except Exception:
        print(f"[{env_name}] {op}: HTTP {status} (JSON 아님) body={body[:260]!r}")

def main():
    odii_key = os.environ.get("ODII_KEY", "").strip()
    tour_key = os.environ.get("TOURAPI_KEY", "").strip()
    if not odii_key:
        print("ODII_KEY가 없어요. 저장소 Secrets에 ODII_KEY를 등록해 주세요.")
    for op in OPS_ODII if odii_key else []:
        call(ODII, op, odii_key, "ODII")
    if tour_key:
        for op in OPS_ENG:
            call(ENG, op, tour_key, "ENG")

if __name__ == "__main__":
    main()
