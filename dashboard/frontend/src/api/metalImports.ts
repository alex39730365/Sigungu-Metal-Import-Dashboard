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
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API 요청 실패 (${res.status}): ${detail}`);
  }
  return res.json() as Promise<T>;
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
