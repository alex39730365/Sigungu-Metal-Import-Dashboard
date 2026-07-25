import { useEffect, useState } from "react";
import {
  cleanCompanyName,
  fetchRegionCompanies,
  getDARTSearchUrl,
  RegionCompaniesResult,
  RegionCompany,
} from "../utils/companyMapper";

interface Props {
  regionName: string | null;
}

export default function RegionalCompanyPanel({ regionName }: Props) {
  const [companies, setCompanies] = useState<RegionCompany[]>([]);
  const [indexLoaded, setIndexLoaded] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedKeyword(keyword), 400);
    return () => clearTimeout(timer);
  }, [keyword]);

  useEffect(() => {
    if (!regionName) {
      setCompanies([]);
      setIndexLoaded(false);
      setStatusMessage("");
      return;
    }
    setLoading(true);
    setError(null);
    fetchRegionCompanies(regionName, debouncedKeyword)
      .then((result: RegionCompaniesResult) => {
        setCompanies(result.companies);
        setIndexLoaded(result.indexLoaded);
        setStatusMessage(result.message);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [regionName, debouncedKeyword]);

  if (!regionName) {
    return (
      <div className="w-full h-48 bg-white rounded-2xl border border-gray-200 p-4 shadow-sm flex items-center justify-center text-gray-500 text-sm">
        지도 또는 차트에서 시군구를 선택하면 본사/등록 사업장 기준 주요 기업이 표시됩니다.
      </div>
    );
  }

  return (
    <div className="w-full bg-white rounded-2xl border border-gray-200 p-4 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-gray-800 text-sm font-semibold">
          {regionName} · 본사 및 등록 사업장 기준 주요 기업
        </h3>
        <span
          className="text-gray-400 text-xs cursor-help select-none"
          title="관세청 통계는 수입 납세의무자의 등록 주소(본사/사업장) 기준으로 집계됩니다. 실제 공장 수요와 다를 수 있으며, DART에 등록된 기업 중 본사/등록 주소가 해당 시군구에 위치한 기업입니다."
        >
          ⓘ
        </span>
      </div>

      <input
        type="text"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        placeholder="기업명 키워드 (예: 철강, 알루미늄, 포스코)"
        className="w-full text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-sky-200 focus:border-sky-400 mb-3"
      />

      {loading && <p className="text-gray-500 text-sm">불러오는 중...</p>}
      {error && <p className="text-red-600 text-sm">{error}</p>}

      {!loading && !error && companies.length === 0 && (
        <div className="text-gray-400 text-sm space-y-1">
          <p>
            {debouncedKeyword
              ? "검색 조건에 맞는 DART 기업 정보가 없습니다."
              : "매핑된 DART 기업 정보가 없습니다."}
          </p>
          {statusMessage && !indexLoaded && (
            <p className="text-amber-600 text-xs">{statusMessage}</p>
          )}
        </div>
      )}

      {!loading && !error && companies.length > 0 && (
        <div className="flex flex-wrap gap-2 max-h-60 overflow-y-auto">
          {companies.map((company) => (
            <a
              key={company.corp_code}
              href={getDARTSearchUrl(company.corp_name)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center px-2.5 py-1 rounded-full text-xs bg-gray-50 border border-gray-200 hover:bg-sky-50 hover:border-sky-200 hover:text-sky-700 transition-colors"
              title={`${company.adres}${
                company.stock_code
                  ? ` · 종목코드 ${company.stock_code}`
                  : ""
              }`}
            >
              {cleanCompanyName(company.corp_name)}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
