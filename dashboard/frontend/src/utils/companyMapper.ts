export interface RegionCompany {
  corp_code: string;
  corp_name: string;
  stock_code: string;
  adres: string;
  induty_code: string;
  induty_name?: string;
  ceo_nm?: string;
  phn_no?: string;
  fax_no?: string;
  bizr_no?: string;
  hm_url?: string;
  revenue?: string;
  op_profit?: string;
  fin_year?: string;
  fs_type?: string;
}

interface RegionCompanyResponse {
  companies: RegionCompany[];
  index_loaded: boolean;
  message: string;
}

export interface RegionCompaniesResult {
  companies: RegionCompany[];
  indexLoaded: boolean;
  message: string;
}

const BASE_URL = `${import.meta.env.VITE_API_BASE_URL ?? ""}/api`;

export async function fetchRegionCompanies(
  regionName: string,
  keyword?: string
): Promise<RegionCompaniesResult> {
  const params = new URLSearchParams({ region_name: regionName });
  if (keyword?.trim()) {
    params.set("keyword", keyword.trim());
  }
  const res = await fetch(`${BASE_URL}/region-companies?${params.toString()}`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API 요청 실패 (${res.status}): ${detail}`);
  }
  const data: RegionCompanyResponse = await res.json();
  return {
    companies: data.companies,
    indexLoaded: data.index_loaded,
    message: data.message,
  };
}

export function cleanCompanyName(name: string): string {
  return name
    .replace(/[㈜]/g, "")
    .replace(/[(（](주|유|사|재|합|법)[)）]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function getDARTSearchUrl(companyName: string): string {
  const clean = cleanCompanyName(companyName);
  return `https://dart.fss.or.kr/dsab001/main.do?autoSearch=true&textCrpNM=${encodeURIComponent(
    clean
  )}`;
}

export function getDARTOverviewUrl(corpCode: string): string {
  return `https://dart.fss.or.kr/html/MDC/CFNKDagSearch/DJCorpSearch?pComCode=${encodeURIComponent(
    corpCode
  )}`;
}

export function formatKoreanEok(raw: string | number | undefined): string {
  if (raw === undefined || raw === '') return '정보 없음';
  const v = typeof raw === 'string' ? Number(raw.replace(/,/g, '')) : raw;
  if (Number.isNaN(v) || v === 0) return '정보 없음';
  const eok = Math.round(v / 1e8);
  return eok === 0 ? '정보 없음' : `${eok.toLocaleString()}억 원`;
}
