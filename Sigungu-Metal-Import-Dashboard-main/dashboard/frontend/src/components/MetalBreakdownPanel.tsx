import { useEffect, useState } from "react";
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { fetchRegionBreakdown } from "../api/metalImports";
import { MetalBreakdownItem } from "../types";
import { formatUsd } from "../utils/formatUsd";

interface Props {
  regionName: string | null;
}

const METAL_COLORS: Record<string, string> = {
  철강: "#475569",
  구리: "#f97316",
  알루미늄: "#0ea5e9",
  니켈: "#8b5cf6",
  아연: "#eab308",
  납: "#4b5563",
  주석: "#06b6d4",
  마그네슘: "#ec4899",
  코발트: "#3b82f6",
  몰리브덴: "#f43f5e",
  텅스텐: "#6366f1",
  탄탈륨: "#d946ef",
  티타늄: "#14b8a6",
  지르코늄: "#0d9488",
  안티모니: "#f59e0b",
  비스무트: "#64748b",
  망간: "#a855f7",
  기타희유금속: "#9ca3af",
  리튬화합물: "#22c55e",
  기타: "#f472b6",
};

export default function MetalBreakdownPanel({ regionName }: Props) {
  const [data, setData] = useState<MetalBreakdownItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const visibleData = data.filter((d) => d.ratio_pct > 0);
  const sortedData = [...visibleData].sort((a, b) => b.ratio_pct - a.ratio_pct);

  useEffect(() => {
    if (!regionName) {
      setData([]);
      return;
    }
    setLoading(true);
    setError(null);
    fetchRegionBreakdown(regionName)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [regionName]);

  if (!regionName) {
    return (
      <div className="w-full h-72 bg-white rounded-2xl border border-gray-200 p-4 shadow-sm flex items-center justify-center text-gray-500 text-sm">
        지도 또는 차트에서 시군구를 클릭하면 금속별 수입 비율이 표시됩니다.
      </div>
    );
  }

  return (
    <div className="w-full h-[540px] bg-white rounded-2xl border border-gray-200 p-4 shadow-sm flex flex-col">
      <h3 className="text-gray-800 text-sm font-semibold mb-2">
        {regionName} · 금속별 수입 비율
      </h3>

      {loading && <p className="text-gray-500 text-sm">불러오는 중...</p>}
      {error && <p className="text-red-600 text-sm">{error}</p>}

      {!loading && !error && (
        <div className="flex flex-col flex-1 min-h-0">
          <div className="h-48 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={sortedData}
                  dataKey="ratio_pct"
                  nameKey="metal_category"
                  innerRadius={45}
                  outerRadius={80}
                  paddingAngle={2}
                >
                  {sortedData.map((entry) => (
                    <Cell
                      key={entry.metal_category}
                      fill={METAL_COLORS[entry.metal_category] ?? "#64748b"}
                    />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value: number, _name, props: any) => [
                    `${value}% (${formatUsd(props.payload.import_usd)})`,
                    props.payload.metal_category,
                  ]}
                  contentStyle={{ backgroundColor: "#ffffff", border: "1px solid #e2e8f0" }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto mt-3 pr-1">
            {sortedData.map((entry) => {
              const color = METAL_COLORS[entry.metal_category] ?? "#64748b";
              return (
                <div
                  key={entry.metal_category}
                  className="py-2 border-b border-gray-100 last:border-0"
                >
                  <div className="flex items-center justify-between text-sm">
                    <div className="flex items-center min-w-0">
                      <span
                        className="w-2.5 h-2.5 rounded-full shrink-0"
                        style={{ backgroundColor: color }}
                      />
                      <span className="ml-2 text-gray-700 truncate">
                        {entry.metal_category}
                      </span>
                    </div>
                    <div className="flex items-center ml-3 shrink-0">
                      <span className="text-gray-500 text-xs mr-3">
                        {formatUsd(entry.import_usd)}
                      </span>
                      <span className="font-medium text-gray-800 w-12 text-right">
                        {entry.ratio_pct.toFixed(1)}%
                      </span>
                    </div>
                  </div>
                  <div className="w-full bg-gray-100 rounded-full h-1.5 mt-1.5 overflow-hidden">
                    <div
                      className="h-1.5 rounded-full"
                      style={{ width: `${Math.min(entry.ratio_pct, 100)}%`, backgroundColor: color }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
