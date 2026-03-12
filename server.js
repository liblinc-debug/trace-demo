const express = require('express');
const path = require('path');
const fs = require('fs');
const cors = require('cors');

const app = express();
const LOG_DIR = path.join(__dirname, 'logs');

app.use(cors());
app.use(express.json());

app.get('/api/logs', (req, res) => {
  fs.readdir(LOG_DIR, (err, files) => {
    if (err) return res.status(500).json({ error: err.message });
    const csvs = files.filter(f => f.endsWith('.csv'));
    res.json(csvs);
  });
});

app.get('/api/logs/:name', (req, res) => {
  const name = req.params.name;
  const filePath = path.join(LOG_DIR, name);
  if (!fs.existsSync(filePath)) return res.status(404).send('Not found');
  res.sendFile(filePath);
});

// serve built frontend
app.use(express.static(path.join(__dirname, 'dist')));
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'dist', 'index.html'));
});

const port = process.env.PORT || 4000;
app.listen(port, () => {
  console.log(`Server listening on http://localhost:${port}`);
});