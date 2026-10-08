const test = require('node:test');
const assert = require('node:assert/strict');
const { parseFlightQuery, buildFlightQuery } = require('./server');

test('getChartRangeIndices maps a dragged chart range to point indexes', async () => {
  const { getChartRangeIndices } = await import('./src/chartRange.mjs');

  assert.deepEqual(getChartRangeIndices({ batch: [{ startValue: 2, endValue: 7 }] }, 10), [2, 7]);
  assert.deepEqual(getChartRangeIndices({ areas: [{ coordRange: [1, 6] }] }, 10), [1, 6]);
  assert.deepEqual(getChartRangeIndices({ startValue: 8, endValue: 3 }, 10), [3, 8]);
  assert.deepEqual(getChartRangeIndices({ start: 20, end: 80 }, 11), [2, 8]);
  assert.equal(getChartRangeIndices({ startValue: 3, endValue: 3 }, 10), null);
});

test('parseFlightQuery validates and de-duplicates the selection', () => {
  const result = parseFlightQuery({
    aircraftIds: 'uav-2-20,uav-2-20,uav-2-203',
    start: '2026-09-30T00:00:00.000Z',
    end: '2026-09-30T01:00:00.000Z'
  });

  assert.deepEqual(result.aircraftIds, ['uav-2-20', 'uav-2-203']);
  assert.equal(result.startMs, 1790726400000);
  assert.equal(result.endMs, 1790730000000);
});

test('parseFlightQuery rejects unsafe aircraft IDs and reversed time ranges', () => {
  assert.throws(
    () => parseFlightQuery({ aircraftIds: "uav') OR 1=1", start: '2026-09-30', end: '2026-10-01' }),
    /飞机编号不合法/
  );
  assert.throws(
    () => parseFlightQuery({ aircraftIds: 'uav-2-20', start: '2026-10-01', end: '2026-09-30' }),
    /飞行时段不合法/
  );
});

test('buildFlightQuery maps ClickHouse columns to the existing replay fields', () => {
  const sql = buildFlightQuery({
    aircraftIds: ['uav-2-20'],
    startMs: 1000,
    endMs: 2000
  });

  assert.match(sql, /aircraft_id IN \('uav-2-20'\)/);
  assert.match(sql, /rsrp_dbm AS Signal_dBm/);
  assert.match(sql, /ts_unix_ms AS TimestampMs/);
  assert.match(sql, /latitude_deg AS Latitude/);
  assert.match(sql, /ORDER BY aircraft_id, ts_unix_ms/);
});
