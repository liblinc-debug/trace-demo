const express = require('express');
const path = require('path');
const fs = require('fs');
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

// serve built frontend
app.use(express.static(path.join(__dirname, 'dist')));
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'dist', 'index.html'));
});

const port = process.env.PORT || 4000;
app.listen(port, '0.0.0.0', () => {
  console.log(`Server listening on http://0.0.0.0:${port}`);
});