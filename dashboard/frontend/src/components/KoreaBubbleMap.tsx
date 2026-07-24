import { RegionSummary } from "../types";

/**
 * 대한민국 남한 영역 근사 경계 (버블 위치 계산용 투영 기준 박스).
 * 실제 시군구 경계(TopoJSON)를 붙이려면 react-simple-maps + 공식 행정구역
 * TopoJSON(예: 통계청 SGIS, VWorld)으로 이 컴포넌트를 교체하세요.
 */
const BOUNDS = {
  minLon: 125.0,
  maxLon: 130.0,
  minLat: 33.0,
  maxLat: 38.7,
};

const VIEW_WIDTH = 480;
const VIEW_HEIGHT = 560;

function project(lat: number, lon: number): { x: number; y: number } {
  const x = ((lon - BOUNDS.minLon) / (BOUNDS.maxLon - BOUNDS.minLon)) * VIEW_WIDTH;
  const y =
    VIEW_HEIGHT - ((lat - BOUNDS.minLat) / (BOUNDS.maxLat - BOUNDS.minLat)) * VIEW_HEIGHT;
  return { x, y };
}

interface Props {
  regions: RegionSummary[];
  selectedRegion: string | null;
  onSelectRegion: (regionName: string) => void;
}

export default function KoreaBubbleMap({ regions, selectedRegion, onSelectRegion }: Props) {
  const maxValue = Math.max(...regions.map((r) => r.total_import_usd), 1);

  const radiusScale = (value: number) => {
    const minR = 10;
    const maxR = 34;
    return minR + (Math.sqrt(value / maxValue) || 0) * (maxR - minR);
  };

  return (
    <div className="w-full flex flex-col items-center">
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        className="w-full max-w-md rounded-2xl bg-white border border-gray-200 shadow-sm"
      >
        <rect
          x={4}
          y={4}
          width={VIEW_WIDTH - 8}
          height={VIEW_HEIGHT - 8}
          rx={24}
          fill="#f8fafc"
          stroke="#e2e8f0"
        />
        <text x={16} y={28} fill="#64748b" fontSize={14}>
          대한민국 (근사 좌표 기반 버블맵)
        </text>

        {regions
          .filter((r) => r.lat !== null && r.lon !== null)
          .map((r) => {
            const { x, y } = project(r.lat as number, r.lon as number);
            const isSelected = r.region_nm === selectedRegion;
            return (
              <g
                key={r.region_nm}
                transform={`translate(${x}, ${y})`}
                onClick={() => onSelectRegion(r.region_nm)}
                className="cursor-pointer"
              >
                <circle
                  r={radiusScale(r.total_import_usd)}
                  fill={isSelected ? "#38bdf8" : "#f59e0b"}
                  fillOpacity={0.75}
                  stroke={isSelected ? "#0ea5e9" : "#b45309"}
                  strokeWidth={isSelected ? 3 : 1.5}
                />
                <title>
                  {r.region_nm}: ${r.total_import_usd.toLocaleString()}
                </title>
              </g>
            );
          })}
      </svg>
      <p className="text-xs text-gray-500 mt-2">
        버블 크기 = 수입금액(USD) 규모 · 원을 클릭하면 상세 비율을 확인할 수 있습니다.
      </p>
    </div>
  );
}
