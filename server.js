const express = require('express');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');
const cors = require('cors');

const envFile = path.join(__dirname, '.env');
if (fs.existsSync(envFile)) {
  fs.readFileSync(envFile, 'utf8').split(/\r?\n/).forEach(line => {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)\s*$/);
    if (!match || process.env[match[1]] !== undefined) return;
    const value = match[2].trim();
    process.env[match[1]] = /^(['"]).*\1$/.test(value) ? value.slice(1, -1) : value;
  });
}

const app = express();
const LOG_DIR = path.join(__dirname, 'logs');
const CLICKHOUSE_URL = process.env.CLICKHOUSE_HTTP_URL || 'http://10.252.2.13:8123';
const CLICKHOUSE_DATABASE = process.env.CLICKHOUSE_DATABASE || 'uav_logs';
const CLICKHOUSE_TABLE = process.env.CLICKHOUSE_TABLE || 'comm_report';
const CLICKHOUSE_USER = process.env.CLICKHOUSE_USER || 'default';
const CLICKHOUSE_PASSWORD = process.env.CLICKHOUSE_PASSWORD || '';
const CLICKHOUSE_TIMEOUT_MS = Math.max(1000, Number(process.env.CLICKHOUSE_TIMEOUT_S || 8) * 1000);
const CLICKHOUSE_MAX_ROWS = Math.max(1, Number(process.env.CLICKHOUSE_MAX_ROWS || 500000));

if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(CLICKHOUSE_DATABASE) ||
    !/^[A-Za-z_][A-Za-z0-9_]*$/.test(CLICKHOUSE_TABLE)) {
  throw new Error('CLICKHOUSE_DATABASE 和 CLICKHOUSE_TABLE 必须是合法标识符');
}

const FLIGHT_COLUMNS = `
  aircraft_id AS Aircraft_ID,
  ts_unix_ms AS TimestampMs,
  formatDateTime(fromUnixTimestamp64Milli(ts_unix_ms), '%Y-%m-%d %H:%i:%S', 'Asia/Shanghai') AS Timestamp,
  latitude_deg AS Latitude,
  longitude_deg AS Longitude,
  altitude_m AS \`Altitude(m)\`,
  speed_m_s AS \`Speed(m/s)\`,
  climb_m_s AS \`Climb(m/s)\`,
  heading_deg AS \`Heading(deg)\`,
  packet_loss_percent AS \`Loss_Rate(%)\`,
  latency_ms AS \`Avg_Ping(ms)\`,
  dist_to_arm_pt_m AS \`Dist_to_Arm_Pt(m)\`,
  flight_distance_m AS \`Flight_Dist(m)\`,
  wp_speed_m_s AS \`WP_Speed(m/s)\`,
  wp_radius_m AS \`WP_Radius(m)\`,
  wp_accel_m_s2 AS \`WP_Accel(m/s2)\`,
  access_technology AS Network,
  band AS Band,
  cell_id AS Cell_ID,
  pci AS PCI,
  rsrp_dbm AS Signal_dBm,
  rsrp_dbm AS RSRP,
  rsrq_db AS RSRQ,
  sinr_db AS SNR,
  rssi_dbm AS RSSI,
  jitter_ms AS \`Jitter(ms)\``;

app.use(cors());
app.use(express.json());

async function queryClickHouse(sql, format = 'JSONEachRow') {
  const url = new URL(CLICKHOUSE_URL);
  url.searchParams.set('database', CLICKHOUSE_DATABASE);
  url.searchParams.set('default_format', format);
  url.searchParams.set('max_execution_time', String(Math.ceil(CLICKHOUSE_TIMEOUT_MS / 1000)));
  url.searchParams.set('max_result_rows', String(CLICKHOUSE_MAX_ROWS));
  url.searchParams.set('result_overflow_mode', 'throw');

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), CLICKHOUSE_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Basic ${Buffer.from(`${CLICKHOUSE_USER}:${CLICKHOUSE_PASSWORD}`).toString('base64')}`,
        'Content-Type': 'text/plain; charset=utf-8'
      },
      body: sql,
      signal: controller.signal
    });
    const text = await response.text();
    if (!response.ok) {
      const error = new Error(`ClickHouse ${response.status}: ${text.trim()}`);
      error.statusCode = text.includes('max_result_rows') ? 413 : 502;
      throw error;
    }
    return text;
  } catch (error) {
    if (error.name === 'AbortError') {
      const timeoutError = new Error('ClickHouse 查询超时');
      timeoutError.statusCode = 504;
      throw timeoutError;
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function parseFlightQuery(query) {
  const aircraftIds = String(query.aircraftIds || '')
    .split(',')
    .map(value => value.trim())
    .filter(Boolean);
  const uniqueAircraftIds = [...new Set(aircraftIds)];
  if (!uniqueAircraftIds.length) {
    const error = new Error('请至少选择一个飞机编号');
    error.statusCode = 400;
    throw error;
  }
  if (uniqueAircraftIds.length > 20 || uniqueAircraftIds.some(id => !/^[A-Za-z0-9_.:-]{1,128}$/.test(id))) {
    const error = new Error('飞机编号不合法或选择数量超过 20');
    error.statusCode = 400;
    throw error;
  }

  const startMs = Date.parse(String(query.start || ''));
  const endMs = Date.parse(String(query.end || ''));
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || startMs >= endMs) {
    const error = new Error('飞行时段不合法，结束时间必须晚于开始时间');
    error.statusCode = 400;
    throw error;
  }
  return { aircraftIds: uniqueAircraftIds, startMs, endMs };
}

function buildFlightQuery({ aircraftIds, startMs, endMs }, format = 'JSONEachRow') {
  const ids = aircraftIds.map(id => `'${id}'`).join(', ');
  return `SELECT ${FLIGHT_COLUMNS}
FROM \`${CLICKHOUSE_DATABASE}\`.\`${CLICKHOUSE_TABLE}\`
WHERE aircraft_id IN (${ids})
  AND ts_unix_ms >= ${startMs}
  AND ts_unix_ms <= ${endMs}
  AND latitude_deg IS NOT NULL
  AND longitude_deg IS NOT NULL
  AND altitude_m >= 0
ORDER BY aircraft_id, ts_unix_ms
FORMAT ${format}`;
}

function sendClickHouseError(res, error) {
  console.error('飞行数据请求失败:', error.message);
  const status = error.statusCode || 502;
  const message = status === 413
    ? '所选时段数据量过大，请缩短时间范围或减少飞机数量'
    : error.message;
  res.status(status).json({ error: message });
}

app.get('/api/flights/aircraft', async (req, res) => {
  try {
    const sql = `SELECT
  aircraft_id,
  count() AS row_count,
  min(ts_unix_ms) AS min_ts,
  max(ts_unix_ms) AS max_ts
FROM \`${CLICKHOUSE_DATABASE}\`.\`${CLICKHOUSE_TABLE}\`
WHERE aircraft_id != ''
  AND latitude_deg IS NOT NULL
  AND longitude_deg IS NOT NULL
  AND altitude_m >= 0
GROUP BY aircraft_id
ORDER BY aircraft_id
FORMAT JSONEachRow`;
    const text = await queryClickHouse(sql);
    const aircraft = text.trim()
      ? text.trim().split('\n').map(line => JSON.parse(line))
      : [];
    res.json(aircraft);
  } catch (error) {
    sendClickHouseError(res, error);
  }
});

app.get('/api/flights', async (req, res) => {
  try {
    const selection = parseFlightQuery(req.query);
    const sql = buildFlightQuery(selection);
    console.log(`[ClickHouse SQL]\n${sql}`);
    const text = await queryClickHouse(sql);
    const rows = text.trim()
      ? text.trim().split('\n').map(line => JSON.parse(line))
      : [];
    const tracksByAircraft = new Map(selection.aircraftIds.map(id => [id, []]));
    rows.forEach(row => {
      const points = tracksByAircraft.get(row.Aircraft_ID);
      if (points) points.push(row);
    });
    const tracks = selection.aircraftIds.map(id => ({ name: id, points: tracksByAircraft.get(id) }));
    res.json({ tracks, total: rows.length });
  } catch (error) {
    sendClickHouseError(res, error);
  }
});

app.get('/api/flights/export', async (req, res) => {
  try {
    const selection = parseFlightQuery(req.query);
    const csv = await queryClickHouse(buildFlightQuery(selection, 'CSVWithNames'), 'CSVWithNames');
    const startDate = new Date(selection.startMs).toISOString().slice(0, 10);
    const endDate = new Date(selection.endMs).toISOString().slice(0, 10);
    res.setHeader('Content-Type', 'text/csv; charset=utf-8');
    res.setHeader('Content-Disposition', `attachment; filename="flight_${startDate}_${endDate}.csv"`);
    res.send(`\uFEFF${csv}`);
  } catch (error) {
    sendClickHouseError(res, error);
  }
});

app.get('/api/logs', (req, res) => {
  const { dir } = req.query;
  if (dir) {
    const targetDir = path.join(LOG_DIR, dir);
    if (!fs.existsSync(targetDir) || !fs.statSync(targetDir).isDirectory()) {
      return res.status(404).json({ error: '目录不存在' });
    }
    const files = fs.readdirSync(targetDir)
      .filter(f => f.endsWith('.csv'))
      .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }));
    return res.json(files);
  }

  const dirs = fs.readdirSync(LOG_DIR, { withFileTypes: true })
    .filter(item => item.isDirectory())
    .map(item => item.name)
    .sort((a, b) => b.localeCompare(a, undefined, { numeric: true, sensitivity: 'base' }));

  res.json(dirs);
});

app.get('/api/logs/file', (req, res) => {
  const { dir, name } = req.query;
  if (!dir || !name) return res.status(400).json({ error: '缺少参数 dir 或 name' });
  const filePath = path.join(LOG_DIR, dir, name);
  if (!fs.existsSync(filePath)) return res.status(404).send('Not found');
  res.sendFile(filePath);
});

app.get('/api/logs/zip', (req, res) => {
  const { dir } = req.query;
  if (!dir) return res.status(400).json({ error: '缺少参数 dir' });

  const targetDir = path.join(LOG_DIR, dir);
  if (!fs.existsSync(targetDir) || !fs.statSync(targetDir).isDirectory()) {
    return res.status(404).json({ error: '目录不存在' });
  }

  const files = fs.readdirSync(targetDir)
    .map(name => {
      const fullPath = path.join(targetDir, name);
      return fs.existsSync(fullPath) && fs.statSync(fullPath).isFile() ? name : null;
    })
    .filter(Boolean);

  if (!files.length) {
    return res.status(404).json({ error: '目录下没有可下载的日志文件' });
  }

  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'trace-demo-'));
  const zipPath = path.join(tmpDir, `${dir}.zip`);
  const downloadName = `${dir}.zip`;
  const zipArgs = ['-q', '-j', zipPath, ...files];

  let cleaned = false;
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    try {
      if (fs.existsSync(zipPath)) fs.unlinkSync(zipPath);
    } catch (err) {
      console.warn('清理 zip 临时文件失败:', err);
    }
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch (err) {
      console.warn('清理 zip 临时目录失败:', err);
    }
  };

  const zipper = spawn('zip', zipArgs, { cwd: targetDir });
  let stderr = '';
  zipper.stderr.on('data', chunk => {
    stderr += chunk.toString();
  });
  zipper.on('error', err => {
    cleanup();
    res.status(500).json({ error: `zip 命令执行失败: ${err.message}` });
  });
  zipper.on('close', code => {
    if (code !== 0) {
      cleanup();
      return res.status(500).json({ error: `zip 打包失败: ${stderr || `exit code ${code}`}` });
    }
    res.download(zipPath, downloadName, err => {
      cleanup();
      if (err && !res.headersSent) {
        res.status(500).json({ error: 'zip 下载失败' });
      }
    });
  });
});

// serve built frontend
app.use(express.static(path.join(__dirname, 'dist')));
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'dist', 'index.html'));
});

if (require.main === module) {
  const port = process.env.PORT || 4000;
  const host = process.env.BACKEND_HOST || '0.0.0.0';
  app.listen(port, host, () => {
    console.log(`Server listening on http://${host}:${port}`);
  });
}

module.exports = { app, parseFlightQuery, buildFlightQuery };
