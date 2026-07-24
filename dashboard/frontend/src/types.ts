export interface RegionSummary {
  region_nm: string;
  lat: number | null;
  lon: number | null;
  total_import_usd: number;
  total_import_cnt: number;
}

export interface MetalBreakdownItem {
  metal_category: string;
  import_usd: number;
  import_cnt: number;
  ratio_pct: number;
}

export interface TimeseriesPoint {
  year_month: string;
  import_usd: number;
  import_cnt: number;
}

export interface MetalSummary {
  metal_category: string;
  total_import_usd: number;
  total_import_cnt: number;
}

export interface MetalRegionItem {
  region_nm: string;
  lat: number | null;
  lon: number | null;
  import_usd: number;
  import_cnt: number;
  ratio_pct: number;
}
