import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchMetalRegions, fetchMetals } from "../api/metalImports";
import { MetalRegionItem, MetalSummary } from "../types";
import { formatUsd, formatUsdCompact } from "../utils/formatUsd";

interface Props {
  selectedRegion: string | null;
  onSelectRegion: (regionName: string) => void;
}

const BAR_COLOR = "#38bdf8";
const SELECTED_BAR_COLOR = "#f59e0b";

export default function MetalSearchPanel({
  selectedRegion,
  onSelectRegion,
}: Props) {
  const [metals, setMetals] = useState<MetalSummary[]>([]);
  const [metalLoading, setMetalLoading] = useState(false);
  const [metalError, setMetalError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedMetal, setSelectedMetal] = useState<string | null>(null);

  const [regions, setRegions] = useState<MetalRegionItem[]>([]);
  const [regionLoading, setRegionLoading] = useState(false);
  const [regionError, setRegionError] = useState<string | null>(null);

  useEffect(() => {
    setMetalLoading(true);
    setMetalError(null);
    fetchMetals()
      .then(setMetals)
      .catch((err) => setMetalError(err.message))
      .finally(() => setMetalLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedMetal) {
      setRegions([]);
      return;
    }
    setRegionLoading(true);
    setRegionError(null);
    fetchMetalRegions(selectedMetal, 20)
      .then(setRegions)
      .catch((err) => setRegionError(err.message))
      .finally(() => setRegionLoading(false));
  }, [selectedMetal]);

  const filteredMetals = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    if (!term) return metals.slice(0, 20);
    return metals.filter((m) => m.metal_category.toLowerCase().includes(term));
  }, [metals, searchTerm]);

  const chartData = useMemo(
    () => [...regions].sort((a, b) => b.import_usd - a.import_usd),
    [regions]
  );

  const topRegion = chartData[0];

  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-4 shadow-sm flex flex-col gap-4">
      <h3 className="text-gray-800 text-sm font-semibold">금속으로 시군구 찾기</h3>

      <input
        value={searchTerm}
        onChange={(e) => {
          setSearchTerm(e.target.value);
          if (selectedMetal && !e.target.value.includes(selectedMetal)) {
            // 검색어가 달라지면 선택 유지 (사용자가 클릭 전까지)
          }
        }}
        placeholder="금속 검색 (예: 구리, 알루미늄)..."
        className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-sky-500"
      />

      {metalLoading && <p className="text-gray-500 text-sm">금속 목록 로드 중...</p>}
      {metalError && <p className="text-red-600 text-sm">{metalError}</p>}

      {!metalLoading && !metalError && (
        <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto">
          {filteredMetals.map((m) => (
            <button
              key={m.metal_category}
              onClick={() => setSelectedMetal(m.metal_category)}
              className={`px-2 py-1 rounded-full text-xs border transition-colors ${
                selectedMetal === m.metal_category
                  ? "bg-sky-600 text-white border-sky-600"
                  : "bg-gray-50 text-gray-700 border-gray-200 hover:bg-gray-100"
              }`}
            >
              {m.metal_category}
            </button>
          ))}
          {filteredMetals.length === 0 && (
            <span className="text-gray-400 text-xs">검색 결과가 없습니다.</span>
          )}
        </div>
      )}

      {selectedMetal && (
        <div className="border-t border-gray-100 pt-3 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h4 className="text-gray-800 text-sm font-semibold">
              {selectedMetal} 수입 상위 시군구
              <span className="ml-1 font-normal text-gray-400">· 단위: USD</span>
            </h4>
            {topRegion && (
              <span className="text-xs text-gray-500">
                1위: <span className="font-medium text-gray-800">{topRegion.region_nm}</span> (
                {formatUsd(topRegion.import_usd)})
              </span>
            )}
          </div>

          {regionLoading && <p className="text-gray-500 text-sm">불러오는 중...</p>}
          {regionError && <p className="text-red-600 text-sm">{regionError}</p>}

          {!regionLoading && !regionError && regions.length > 0 && (
            <>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} layout="vertical" margin={{ left: 24, right: 16 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis
                      type="number"
                      stroke="#6b7280"
                      tick={{ fontSize: 11 }}
                      tickFormatter={formatUsdCompact}
                    />
                    <YAxis
                      type="category"
                      dataKey="region_nm"
                      stroke="#6b7280"
                      tick={{ fontSize: 11 }}
                      width={110}
                    />
                    <Tooltip
                      formatter={(value: number) => formatUsd(value)}
                      contentStyle={{ backgroundColor: "#ffffff", border: "1px solid #e2e8f0" }}
                      labelStyle={{ color: "#1f2937" }}
                    />
                    <Bar
                      dataKey="import_usd"
                      radius={[0, 6, 6, 0]}
                      onClick={(entry: any) => onSelectRegion(entry.region_nm)}
                      cursor="pointer"
                    >
                      {chartData.map((entry) => (
                        <Cell
                          key={entry.region_nm}
                          fill={
                            entry.region_nm === selectedRegion
                              ? SELECTED_BAR_COLOR
                              : BAR_COLOR
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <ul className="divide-y divide-gray-100 max-h-48 overflow-y-auto">
                {regions.map((r) => (
                  <li
                    key={r.region_nm}
                    onClick={() => onSelectRegion(r.region_nm)}
                    className={`flex justify-between py-2 px-2 rounded-lg cursor-pointer transition-colors ${
                      r.region_nm === selectedRegion
                        ? "bg-sky-50 text-sky-700"
                        : "hover:bg-gray-100"
                    }`}
                  >
                    <span className="text-sm">{r.region_nm}</span>
                    <span className="text-gray-500 text-sm">
                      {formatUsd(r.import_usd)} ({r.ratio_pct.toFixed(1)}%)
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {!regionLoading && !regionError && regions.length === 0 && (
            <p className="text-gray-500 text-sm">해당 금속 데이터가 없습니다.</p>
          )}
        </div>
      )}
    </div>
  );
}
