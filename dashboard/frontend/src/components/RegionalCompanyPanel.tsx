import { useEffect, useState } from "react";
import {
  fetchRegionCompanies,
  RegionCompaniesResult,
  RegionCompany,
} from "../utils/companyMapper";
import CompanyDetailModal from "./CompanyDetailModal";

interface Props {
  regionName: string | null;
}

export default function RegionalCompanyPanel({ regionName }: Props) {
  const [companies, setCompanies] = useState<RegionCompany[]>([]);
  const [indexLoaded, setIndexLoaded] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedCompany, setSelectedCompany] = useState<RegionCompany | null>(
    null
  );

  useEffect(() => {
    if (!regionName) {
      setCompanies([]);
      setIndexLoaded(false);
      setStatusMessage("");
      return;
    }
    setLoading(true);
    setError(null);
    fetchRegionCompanies(regionName)
      .then((result: RegionCompaniesResult) => {
        setCompanies(result.companies);
        setIndexLoaded(result.indexLoaded);
        setStatusMessage(result.message);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [regionName]);

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

      {loading && <p className="text-gray-500 text-sm">불러오는 중...</p>}
      {error && <p className="text-red-600 text-sm">{error}</p>}

      {!loading && !error && companies.length === 0 && (
        <div className="text-gray-400 text-sm space-y-1">
          <p>매핑된 DART 기업 정보가 없습니다.</p>
          {statusMessage && !indexLoaded && (
            <p className="text-amber-600 text-xs">{statusMessage}</p>
          )}
        </div>
      )}

      {!loading && !error && companies.length > 0 && (
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {companies.map((company) => (
            <div
              key={company.corp_code}
              onClick={() => setSelectedCompany(company)}
              className="block p-2.5 rounded-lg text-sm bg-gray-50 border border-gray-200 hover:bg-sky-50 hover:border-sky-200 hover:text-sky-700 cursor-pointer transition-colors"
              title="자세히 보려면 클릭"
            >
              <div className="font-semibold text-gray-900">
                {company.corp_name}
              </div>
              <div className="text-xs text-gray-500 mt-1 leading-snug">
                {company.adres}
              </div>
              <div className="text-xs text-gray-500 mt-1">
                {company.induty_name ? company.induty_name : "업종 미확인"}
                {company.induty_code ? ` (${company.induty_code})` : ""}
              </div>
              <div className="text-xs text-gray-400 mt-1">
                {company.ceo_nm ? `대표: ${company.ceo_nm}` : ""}
                {company.phn_no ? ` · 전화: ${company.phn_no}` : ""}
                {company.fax_no ? ` · 팩스: ${company.fax_no}` : ""}
                {company.bizr_no ? ` · 사업자: ${company.bizr_no}` : ""}
              </div>
              {company.hm_url && (
                <div className="text-xs mt-1">
                  <a
                    href={
                      company.hm_url.startsWith("http")
                        ? company.hm_url
                        : `http://${company.hm_url}`
                    }
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="text-sky-600 hover:underline"
                  >
                    홈페이지
                  </a>
                </div>
              )}
            </div>
          ))}
        </div>
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
