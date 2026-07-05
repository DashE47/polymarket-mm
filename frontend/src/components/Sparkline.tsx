// A tiny hand-drawn SVG sparkline (no chart library — keeps it light and fully
// ours). Used in the MarketBar for the recent price line.

interface Props {
  points: number[];
  width?: number;
  height?: number;
  color?: string;
}

export default function Sparkline({ points, width = 280, height = 48, color = "var(--green)" }: Props) {
  if (points.length < 2) {
    return <svg width={width} height={height} role="img" aria-label="price sparkline (no data)" />;
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const step = width / (points.length - 1);
  const coords = points
    .map((p, i) => `${(i * step).toFixed(1)},${(height - ((p - min) / range) * (height - 4) - 2).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={width} height={height} role="img" aria-label="recent price">
      <polyline points={coords} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  );
}
