import { useState } from "react";
import { downloadExcel } from "../api/metalImports";

interface ExportPanelProps {
  selectedRegion: string | null;
}

export default function ExportPanel({ selectedRegion }: ExportPanelProps) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDownload(regionOnly: boolean) {
    setDownloading(true);
    setError(null);
    try {
      await downloadExcel(regionOnly ? selectedRegion : undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "엑셀 내보내기 실패");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="bg-white rounded-2xl border-2 border-sky-200 p-4 shadow-sm">
      <h3 className="text-sky-800 text-sm font-semibold mb-3 flex items-center gap-2">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="w-4 h-4"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        엑셀 내보내기
      </h3>

      <div className="flex flex-col gap-2">
        <button
          type="button"
          onClick={() => handleDownload(false)}
          disabled={downloading}
          className="w-full text-left px-3 py-2 text-sm rounded-lg border border-gray-200 hover:bg-sky-50 hover:text-sky-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {downloading ? "내보내는 중..." : "전체 데이터 엑셀 다운로드"}
        </button>

        <button
          type="button"
          onClick={() => handleDownload(true)}
          disabled={!selectedRegion || downloading}
          className={`w-full text-left px-3 py-2 text-sm rounded-lg border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
            selectedRegion
              ? "border-gray-200 hover:bg-sky-50 hover:text-sky-700"
              : "border-gray-100 text-gray-400"
          }`}
        >
          {selectedRegion
            ? `"${selectedRegion}" 상세 엑셀 다운로드`
            : "시군구를 선택하면 상세 엑셀 다운로드"}
        </button>
      </div>

      {error && <p className="text-red-600 text-xs mt-2">{error}</p>}
    </div>
  );
}
