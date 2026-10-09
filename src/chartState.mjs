export function getChartLegendSelection(seriesNames, savedSelection, defaultName = 'Ping') {
  const hasSavedSelection = savedSelection && Object.keys(savedSelection).length > 0;
  const hasDefaultSeries = seriesNames.includes(defaultName);

  return Object.fromEntries(seriesNames.map(name => [
    name,
    hasSavedSelection
      ? savedSelection[name] === true
      : (hasDefaultSeries ? name === defaultName : true)
  ]));
}

export function getExpandedAxisMax(currentMax, values) {
  const numericValues = values
    .filter(value => value !== null && value !== undefined && value !== '')
    .map(Number)
    .filter(Number.isFinite);
  if (!numericValues.length) return null;

  const seriesMax = Math.max(...numericValues);
  const axisMax = Number(currentMax);
  return !Number.isFinite(axisMax) || seriesMax > axisMax ? seriesMax : null;
}

export function getChartTooltipRows(series, dataIndex) {
  return series.map(item => ({
    name: item.name,
    color: item.itemStyle.color,
    value: item.data[dataIndex]
  }));
}
