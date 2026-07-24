import { useEffect, useState } from "react";

interface Status {
  is_refreshing: boolean;
  last_updated: string | null;
  last_error: string | null;
  row_count: number;
  loaded_from_cache?: boolean;
  cache_file_exists?: boolean;
}

const API_BASE_URL = `${import.meta.env.VITE_API_BASE_URL ?? ""}/api`;

async function fetchStatus(): Promise<Status> {
  const res = await fetch(`${API_BASE_URL}/status`);
  if (!res.ok) throw new Error("status 조회 실패");
  return res.json();
}

interface Props {
  onDataReady: () => void;
}

export default function StatusBar({ onDataReady }: Props) {
  const [status, setStatus] = useState<Status | null>(null);
  const wasRefreshingRef = useState({ current: false })[0];

  useEffect(() => {
    let interval: number;

    const poll = async () => {
      try {
        const s = await fetchStatus();
        setStatus(s);
        if (wasRefreshingRef.current && !s.is_refreshing) {
          onDataReady();
        }
        wasRefreshingRef.current = s.is_refreshing;
      } catch {
        // 서버가 아직 안 떴을 수 있음 - 무시하고 다음 폴링에서 재시도
      }
    };

    poll();
    interval = window.setInterval(poll, 3000);
    return () => window.clearInterval(interval);
  }, [onDataReady, wasRefreshingRef]);

  if (!status) return null;

  return (
    <div className="flex items-center justify-between bg-white border border-gray-200 rounded-xl px-4 py-2 mb-4 text-sm">
      <div className="flex items-center gap-2">
        {status.is_refreshing ? (
          <>
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <span className="text-amber-700">
              관세청 API에서 데이터를 수집하는 중입니다... (수 분 소요될 수 있습니다)
            </span>
          </>
        ) : status.last_error ? (
          <>
            <span className="w-2 h-2 rounded-full bg-red-500" />
            <span className="text-red-600">수집 오류: {status.last_error}</span>
          </>
        ) : (
          <>
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <span className="text-gray-600">
              {status.loaded_from_cache ? "캐시 파일에서 " : ""}
              {status.row_count.toLocaleString()}행 로드됨
              {status.last_updated &&
                ` · 마지막 갱신: ${new Date(status.last_updated).toLocaleString("ko-KR")}`}
            </span>
          </>
        )}
      </div>
      <span className="text-xs text-gray-400">
        월 1회(15~20일) 자동 업데이트
      </span>
    </div>
  );
}
