export function formatUsd(value: number): string {
  return `$${Math.round(value).toLocaleString()}`;
}

export function formatUsdCompact(value: number): string {
  if (Math.abs(value) >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
  if (Math.abs(value) >= 1_000_000) return `$${Math.round(value / 1_000_000)}M`;
  return `$${Math.round(value).toLocaleString()}`;
}
