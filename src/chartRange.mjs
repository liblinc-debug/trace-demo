export function getChartRangeIndices(event, pointCount) {
  if (pointCount < 2) return null;
  const brushRange = event?.areas?.[0]?.coordRange;
  const zoom = brushRange
    ? { startValue: brushRange[0], endValue: brushRange[1] }
    : event?.batch?.[0] || event || {};
  const lastIndex = pointCount - 1;
  const toIndex = (value, percent, fallback) => {
    const numericValue = Number(value);
    if (Number.isFinite(numericValue)) {
      return Math.min(lastIndex, Math.max(0, Math.round(numericValue)));
    }
    const numericPercent = Number(percent);
    return Number.isFinite(numericPercent)
      ? Math.min(lastIndex, Math.max(0, Math.round((numericPercent / 100) * lastIndex)))
      : fallback;
  };
  const firstIndex = toIndex(zoom.startValue, zoom.start, 0);
  const secondIndex = toIndex(zoom.endValue, zoom.end, lastIndex);
  const startIndex = Math.min(firstIndex, secondIndex);
  const endIndex = Math.max(firstIndex, secondIndex);
  return startIndex < endIndex ? [startIndex, endIndex] : null;
}
