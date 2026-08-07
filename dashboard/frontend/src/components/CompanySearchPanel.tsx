import { useEffect, useState } from "react";
import {
  fetchCompanySearch,
  formatKoreanEok,
  RegionCompany,
} from "../utils/companyMapper";
import CompanyDetailModal from "./CompanyDetailModal";

interface Props {
  onSelectRegion: (regionName: string) => void;
}

export default function CompanySearchPanel({ onSelectRegion }: Props) {
  const [searchTerm, setSearchTerm] = useState("");
  const [companies, setCompanies] = useState<RegionCompany[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [selectedCompany, setSelectedCompany] = useState<RegionCompany | null>(null);

  useEffect(() => {
    if (!searchTerm.trim()) {
      setCompanies([]);
      setHasSearched(false);
      return;
    }

    const timer = setTimeout(() => {
      setLoading(true);
      setError(null);
      setHasSearched(true);
      fetchCompanySearch(searchTerm)
        .then((result) => {
          setCompanies(result.companies);
          if (!result.indexLoaded && result.message) {
            setError(result.message);
          }
        })
        .catch((err) => setError(err.message))
        .finally(() => setLoading(false));
    }, 300);

    return () => clearTimeout(timer);
  }, [searchTerm]);

  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-4 shadow-sm flex flex-col gap-3">
      <h3 className="text-gray-800 text-sm font-semibold">기업 검색</h3>

      <input
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        placeholder="기업 검색 (예: 포스코, 철강, 알루미늄)..."
        className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-sky-500"
      />

      {loading && <p className="text-gray-500 text-sm">기업 검색 중...</p>}
      {error && <p className="text-red-600 text-sm">{error}</p>}

      {!loading && hasSearched && companies.length === 0 && (
        <p className="text-gray-400 text-sm">검색 결과가 없습니다.</p>
      )}

      {!loading && companies.length > 0 && (
        <ul className="divide-y divide-gray-100 max-h-96 overflow-y-auto">
          {companies.map((company) => (
            <li
              key={company.corp_code}
              onClick={() => {
                setSelectedCompany(company);
                onSelectRegion(company.sigungu || "");
              }}
              className="py-2.5 px-2 rounded-lg hover:bg-sky-50 cursor-pointer transition-colors"
              title="클릭하면 상세 정보가 표시되고 해당 시군구로 이동"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="text-sm font-semibold text-gray-900">
                  {company.corp_name}
                </div>
                {company.revenue && (
                  <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-emerald-100 text-emerald-700">
                    재무
                  </span>
                )}
              </div>

              <div className="text-xs text-gray-500 mt-1 leading-snug">
                {company.adres || "-"}
              </div>

              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1 text-xs">
                <span className="text-sky-700 font-medium">
                  {company.sigungu || "시군구 미확인"}
                </span>
                {company.induty_name && (
                  <span className="text-gray-500">
                    · {company.induty_name} {company.induty_code ? `(${company.induty_code})` : ""}
                  </span>
                )}
              </div>

              {company.revenue && (
                <div className="mt-1 text-xs font-medium text-emerald-700">
                  매출 {formatKoreanEok(company.revenue)}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {selectedCompany && (
        <CompanyDetailModal
          company={selectedCompany}
          onClose={() => setSelectedCompany(null)}
        />
      )}
    </div>
  );
}
