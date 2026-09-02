const express = require('express');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');
const cors = require('cors');

const app = express();
const LOG_DIR = path.join(__dirname, 'logs');

app.use(cors());
app.use(express.json());

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

const port = process.env.PORT || 4000;
const host = process.env.BACKEND_HOST || '0.0.0.0';
app.listen(port, host, () => {
  console.log(`Server listening on http://${host}:${port}`);
});
