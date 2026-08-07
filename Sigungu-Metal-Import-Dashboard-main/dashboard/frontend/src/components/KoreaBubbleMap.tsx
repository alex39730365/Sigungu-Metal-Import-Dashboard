import { ComposableMap, Geographies, Geography, Marker } from "react-simple-maps";
import { RegionSummary } from "../types";
import { formatUsd } from "../utils/formatUsd";

const GEO_URL =
  "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/gadm/json/skorea-provinces-topo.json";

const MAP_WIDTH = 480;
const MAP_HEIGHT = 560;

interface Props {
  regions: RegionSummary[];
  selectedRegion: string | null;
  onSelectRegion: (regionName: string) => void;
}

export default function KoreaBubbleMap({
  regions,
  selectedRegion,
  onSelectRegion,
}: Props) {
  const maxValue = Math.max(...regions.map((r) => r.total_import_usd), 1);

  const radiusScale = (value: number) => {
    const minR = 4;
    const maxR = 18;
    return minR + (Math.sqrt(value / maxValue) || 0) * (maxR - minR);
  };

  return (
    <div className="w-full flex flex-col items-center">
      <div className="w-full max-w-md rounded-2xl overflow-hidden border border-gray-200 shadow-sm bg-white">
        <ComposableMap
          width={MAP_WIDTH}
          height={MAP_HEIGHT}
          projection="geoMercator"
          projectionConfig={{
            scale: 4200,
            center: [128.2, 36.2],
          }}
        >
          <Geographies geography={GEO_URL}>
            {({ geographies }) =>
              geographies.map((geo) => (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  fill="#f1f5f9"
                  stroke="#cbd5e1"
                  strokeWidth={0.5}
                />
              ))
            }
          </Geographies>

          {regions
            .filter((r) => r.lat !== null && r.lon !== null)
            .map((r) => {
              const isSelected = r.region_nm === selectedRegion;
              return (
                <Marker
                  key={r.region_nm}
                  coordinates={[r.lon as number, r.lat as number]}
                  onClick={() => onSelectRegion(r.region_nm)}
                  style={{ cursor: "pointer" }}
                >
                  <circle
                    r={radiusScale(r.total_import_usd)}
                    fill={isSelected ? "#38bdf8" : "#f59e0b"}
                    fillOpacity={0.75}
                    stroke={isSelected ? "#0ea5e9" : "#b45309"}
                    strokeWidth={isSelected ? 2 : 0.75}
                  />
                  <title>
                    {r.region_nm}: {formatUsd(r.total_import_usd)}
                  </title>
                </Marker>
              );
            })}
        </ComposableMap>
      </div>
      <p className="text-xs text-gray-500 mt-2 text-center">
        버블 크기 = 수입금액(USD) 규모 · 원을 클릭하면 상세 비율을 확인할 수 있습니다.
      </p>
    </div>
  );
}
