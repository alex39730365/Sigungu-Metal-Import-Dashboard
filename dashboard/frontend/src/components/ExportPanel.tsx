import { useState } from "react";
import { downloadExcelUrl } from "../api/metalImports";

interface ExportPanelProps {
  selectedRegion: string | null;
}

export default function ExportPanel({ selectedRegion }: ExportPanelProps) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDownload(regionOnly: boolean) {
    setDownloading(true);
    setError(null);
    const url = downloadExcelUrl(regionOnly ? selectedRegion : undefined);

    try {
      const res = await fetch(url);
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`다운로드 실패 (${res.status}): ${detail}`);
      }

      const blob = await res.blob();
      const safeName = regionOnly && selectedRegion
        ? selectedRegion.replace(/\s+/g, "_")
        : "전체";
      const filename = `sigungu_metal_imports_${safeName}.xlsx`;

      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(a.href);
    } catch (err) {
      setError(err instanceof Error ? err.message : "엑셀 내보내기 실패");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-4 shadow-sm">
      <h3 className="text-gray-800 text-sm font-semibold mb-3">엑셀 내보내기</h3>

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

      {error && (
        <p className="text-red-600 text-xs mt-2">{error}</p>
      )}
    </div>
  );
}
