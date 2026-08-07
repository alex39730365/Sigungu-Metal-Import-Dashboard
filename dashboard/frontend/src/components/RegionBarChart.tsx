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
import { RegionSummary } from "../types";

interface Props {
  regions: RegionSummary[];
  selectedRegion: string | null;
  onSelectRegion: (regionName: string) => void;
}

const COLORS = ["#f59e0b", "#38bdf8", "#a78bfa", "#34d399", "#f472b6", "#fb923c"];

export default function RegionBarChart({ regions, selectedRegion, onSelectRegion }: Props) {
  const data = [...regions].sort((a, b) => b.total_import_usd - a.total_import_usd);

  return (
    <div className="w-full h-72 bg-white rounded-2xl border border-gray-200 p-4 shadow-sm">
      <h3 className="text-gray-800 text-sm font-semibold mb-2">
        시군구별 수입금액 순위 (상위 {data.length}개)
        <span className="ml-1 font-normal text-gray-400">· 단위: 천 USD</span>
      </h3>
      <ResponsiveContainer width="100%" height="85%">
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis type="number" stroke="#6b7280" tick={{ fontSize: 11 }} />
          <YAxis
            type="category"
            dataKey="region_nm"
            stroke="#6b7280"
            tick={{ fontSize: 10 }}
            width={150}
          />
          <Tooltip
            formatter={(value: number) => `${value.toLocaleString()} 천 USD`}
            contentStyle={{ backgroundColor: "#ffffff", border: "1px solid #e2e8f0" }}
            labelStyle={{ color: "#1f2937" }}
          />
          <Bar
            dataKey="total_import_usd"
            radius={[0, 6, 6, 0]}
            onClick={(entry: any) => onSelectRegion(entry.region_nm)}
            cursor="pointer"
          >
            {data.map((entry, idx) => (
              <Cell
                key={entry.region_nm}
                fill={
                  entry.region_nm === selectedRegion ? "#38bdf8" : COLORS[idx % COLORS.length]
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
