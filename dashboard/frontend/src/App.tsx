import { useCallback, useEffect, useState } from "react";
import { fetchRegions } from "./api/metalImports";
import { RegionSummary } from "./types";
import KoreaBubbleMap from "./components/KoreaBubbleMap";
import RegionBarChart from "./components/RegionBarChart";
import MetalBreakdownPanel from "./components/MetalBreakdownPanel";
import MetalSearchPanel from "./components/MetalSearchPanel";
import RegionalCompanyPanel from "./components/RegionalCompanyPanel";
import ExportPanel from "./components/ExportPanel";
import StatusBar from "./components/StatusBar";

export default function App() {
  const [regions, setRegions] = useState<RegionSummary[]>([]);
  const [selectedRegion, setSelectedRegion] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");

  const loadRegions = useCallback(() => {
    setLoading(true);
    fetchRegions()
      .then((data) => {
        setRegions(data);
        setError(null);
        if (data.length > 0 && !selectedRegion) setSelectedRegion(data[0].region_nm);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadRegions();
  }, [loadRegions]);

  const filteredRegions = regions.filter((r) =>
    r.region_nm.toLowerCase().includes(searchTerm.toLowerCase())
  );
  const topRegionsForChart = [...regions]
    .sort((a, b) => b.total_import_usd - a.total_import_usd)
    .slice(0, 20);

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900 p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">시군구별 금속 수입 대시보드</h1>
        <p className="text-gray-500 text-sm mt-1">
          관세청 시군구별 품목별 수출입실적 API 기반 · 비귀금속(철강·비철금속·희유금속·리튬화합물)
        </p>
        <p className="text-gray-400 text-xs mt-0.5">
          공표주기 : 1개월 · 공표시기 : 매월 15일경 수출입 신고의 정정, 취하 등 변경내역을 반영하여 전월까지의 자료를 현행화
        </p>
      </header>

      <StatusBar onDataReady={loadRegions} />

      {loading && regions.length === 0 && (
        <p className="text-gray-500">데이터를 불러오는 중입니다...</p>
      )}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-600 rounded-xl p-4 text-sm mb-4">
          데이터 로드 실패: {error}
          <br />
          상단 상태바를 확인하여 수집이 진행 중이거나 완료될 때까지 기다려주세요.
        </div>
      )}

      {regions.length > 0 && !error && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="flex flex-col gap-6">
            <KoreaBubbleMap
              regions={regions}
              selectedRegion={selectedRegion}
              onSelectRegion={setSelectedRegion}
            />
            <RegionBarChart
              regions={topRegionsForChart}
              selectedRegion={selectedRegion}
              onSelectRegion={setSelectedRegion}
            />
          </div>

          <div className="flex flex-col gap-6">
            <MetalSearchPanel
              selectedRegion={selectedRegion}
              onSelectRegion={setSelectedRegion}
            />
            <ExportPanel selectedRegion={selectedRegion} />
            <MetalBreakdownPanel regionName={selectedRegion} />
            <RegionalCompanyPanel regionName={selectedRegion} />

            <div className="bg-white rounded-2xl border border-gray-200 p-4 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-gray-800 text-sm font-semibold">
                  시군구 목록 ({filteredRegions.length}/{regions.length})
                </h3>
                <input
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  placeholder="시군구 검색..."
                  className="bg-white border border-gray-300 rounded-lg px-2 py-1 text-xs text-gray-900 placeholder-gray-400 w-32 focus:outline-none focus:ring-1 focus:ring-sky-500"
                />
              </div>
              <ul className="divide-y divide-gray-100 max-h-96 overflow-y-auto">
                {filteredRegions.map((r) => (
                  <li
                    key={r.region_nm}
                    onClick={() => setSelectedRegion(r.region_nm)}
                    className={`flex justify-between py-2 px-2 rounded-lg cursor-pointer transition-colors ${
                      r.region_nm === selectedRegion
                        ? "bg-sky-50 text-sky-700"
                        : "hover:bg-gray-100"
                    }`}
                  >
                    <span>{r.region_nm}</span>
                    <span className="text-gray-500">
                      ${r.total_import_usd.toLocaleString()}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
