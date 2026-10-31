import fs from "node:fs/promises";

const key = process.env.DATA_GO_KR_KEY;
if (!key) throw new Error("DATA_GO_KR_KEY secret is missing");

const base = "https://apis.data.go.kr/B551457/run/v2";
const ymd = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Seoul" }).replaceAll("-", "");

async function fetchDataset(endpoint) {
  const url = new URL(`${base}/${endpoint}`);
  url.searchParams.set("serviceKey", key);
  url.searchParams.set("pageNo", "1");
  url.searchParams.set("numOfRows", "1000");
  url.searchParams.set("cond[run_ymd::GTE]", ymd);
  url.searchParams.set("cond[run_ymd::LTE]", ymd);
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  const raw = await response.text();
  if (!response.ok) throw new Error(`${endpoint}: HTTP ${response.status}: ${raw.slice(0, 300)}`);
  let json;
  try { json = JSON.parse(raw); } catch { throw new Error(`${endpoint}: JSON 파싱 실패: ${raw.slice(0, 300)}`); }
  const root = json?.response ?? json;
  const header = root?.header;
  if (header?.resultCode && !["00", "0000"].includes(String(header.resultCode))) {
    throw new Error(`${endpoint}: ${header.resultCode} ${header.resultMsg ?? ""}`);
  }
  const items = root?.body?.items?.item ?? root?.body?.items ?? [];
  if (Array.isArray(items)) return items;
  return items && typeof items === "object" ? [items] : [];
}

const [operationInfo, operationPlan] = await Promise.all([
  fetchDataset("travelerTrainRunInfo2"),
  fetchDataset("travelerTrainRunPlan2")
]);

const data = {
  generatedAt: new Date().toISOString(),
  serviceDate: ymd,
  source: "한국철도공사_열차운행정보 (공공데이터포털)",
  operationInfoCount: operationInfo.length,
  operationPlanCount: operationPlan.length,
  operationInfo,
  operationPlan
};

await fs.mkdir("data", { recursive: true });
await fs.writeFile("data/rail-status.json", JSON.stringify(data, null, 2) + "\n", "utf8");
console.log(`열차 운행정보 ${operationInfo.length}건, 운행계획 ${operationPlan.length}건 저장 (${ymd})`);
