interface Props {
  points: { date: string; score: number }[];
  color: string;
}

/** 90-day health trace. No animation, no shimmer — it is a reference, not a toy. */
export function Sparkline({ points, color }: Props) {
  if (points.length < 2) return <div className="skeleton" style={{ height: 40 }} />;

  const w = 240;
  const h = 40;
  const scores = points.map((p) => p.score);
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const span = Math.max(1, max - min);

  const d = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * w;
      const y = h - 3 - ((p.score - min) / span) * (h - 6);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const lastX = w;
  const lastY = h - 3 - ((scores[scores.length - 1] - min) / span) * (h - 6);

  return (
    <svg className="sparkline" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img"
      aria-label={`Health over ${points.length} days, from ${scores[0]} to ${scores[scores.length - 1]}`}>
      <path d={d} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      <circle cx={lastX - 2} cy={lastY} r={2.4} fill={color} />
    </svg>
  );
}
