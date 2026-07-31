import {
  MetalBreakdownItem,
  MetalRegionItem,
  MetalSummary,
  RegionSummary,
  TimeseriesPoint,
} from "../types";

const BASE_URL = `${import.meta.env.VITE_API_BASE_URL ?? ""}/api`;

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  const contentType = res.headers.get("content-type") ?? "";

  if (!res.ok || contentType.includes("text/html")) {
    const detail = await res.text();
    if (detail.trim().toLowerCase().startsWith("<!doctype") || detail.trim().startsWith("<")) {
      throw new Error(
        `백엔드 API 주소가 잘못되었거나 설정되지 않았습니다. ` +
        `VITE_API_BASE_URL(${BASE_URL})를 확인하고, Cloudflare Pages나 Render 백엔드가 정상적으로 동작하는지 확인하세요.`
      );
    }
    throw new Error(`API 요청 실패 (${res.status}): ${detail}`);
  }

  try {
    return await (res.json() as Promise<T>);
  } catch (err) {
    const text = await res.text();
    throw new Error(
      `응답을 JSON으로 파싱할 수 없습니다. ` +
      `백엔드가 ${BASE_URL}에서 정상적으로 동작하는지, CORS 설정을 확인하세요. ` +
      `(원본 응답: ${text.slice(0, 100)})`
    );
  }
}

export function fetchRegions(): Promise<RegionSummary[]> {
  return getJson<RegionSummary[]>("/regions");
}

export function fetchRegionBreakdown(regionName: string): Promise<MetalBreakdownItem[]> {
  return getJson<MetalBreakdownItem[]>(`/regions/${encodeURIComponent(regionName)}/breakdown`);
}

export function fetchRegionTimeseries(regionName: string): Promise<TimeseriesPoint[]> {
  return getJson<TimeseriesPoint[]>(`/regions/${encodeURIComponent(regionName)}/timeseries`);
}

export function fetchMetals(): Promise<MetalSummary[]> {
  return getJson<MetalSummary[]>("/metals");
}

export function fetchMetalRegions(
  metalCategory: string,
  limit: number = 20
): Promise<MetalRegionItem[]> {
  return getJson<MetalRegionItem[]>(
    `/metals/${encodeURIComponent(metalCategory)}/regions?limit=${limit}`
  );
}

export function downloadExcelUrl(regionName?: string | null): string {
  const params = new URLSearchParams();
  if (regionName) {
    params.set("region_name", regionName);
  }
  const query = params.toString();
  return `${BASE_URL}/export/excel${query ? `?${query}` : ""}`;
}

export async function downloadExcel(regionName?: string | null): Promise<void> {
  const url = downloadExcelUrl(regionName);
  const res = await fetch(url);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`다운로드 실패 (${res.status}): ${detail}`);
  }
  const blob = await res.blob();
  const safeName = regionName ? regionName.replace(/\s+/g, "_") : "전체";
  const filename = `sigungu_metal_imports_${safeName}.xlsx`;

  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}
