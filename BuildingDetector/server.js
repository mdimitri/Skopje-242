const http = require('http');
const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');
const sharp = require('sharp');

const appDir = __dirname;
const projectDir = path.resolve(appDir, '..');
const satelliteDir = path.join(appDir, 'satellite image');
const mosaicPath = path.join(satelliteDir, 'mosaic_full_grid_23x34_z18_mpp_0.5_1795474938.jpg');
const extentPath = path.join(satelliteDir, 'mosaic_full_grid_23x34_z18_mpp_0.5_1795474938.json');
const buildingsPath = path.join(projectDir, 'data', 'osm', 'buildings.json');
const modelPath = path.join(appDir, 'models', 'dinov3s_buildings.onnx');
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.wasm': 'application/wasm', '.onnx': 'application/octet-stream' };
const extent = JSON.parse(fs.readFileSync(extentPath, 'utf8'));

function sendImagePipeline(res, pipeline) {
  res.writeHead(200, { 'Content-Type': 'image/jpeg', 'Cache-Control': 'no-cache' });
  pipeline.on('error', (error) => {
    console.error(error);
    if (!res.headersSent) res.writeHead(500);
    res.end();
  }).pipe(res);
}

function sendFile(res, file, type = mime[path.extname(file)] || 'application/octet-stream', method = 'GET') {
  fs.stat(file, (err, stat) => {
    if (err || !stat.isFile()) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('File not found. Run setup.ps1 and confirm the project OSM data exists.');
      return;
    }
    res.writeHead(200, { 'Content-Type': type, 'Content-Length': stat.size, 'Cache-Control': 'no-cache' });
    if (method === 'HEAD') { res.end(); return; }
    fs.createReadStream(file).pipe(res);
  });
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname === '/api/extent') return sendFile(res, extentPath);
  if (url.pathname === '/api/buildings') return sendFile(res, buildingsPath);
  if (url.pathname === '/api/overview') return sendImagePipeline(res, sharp(mosaicPath).resize(424, 286, { fit: 'fill' }).jpeg({ quality: 78 }));
  if (url.pathname === '/api/tile') {
    const col = Number(url.searchParams.get('col'));
    const row = Number(url.searchParams.get('row'));
    const left = col * 256, top = row * 256;
    const width = Math.min(256, extent.size_px[0] - left);
    const height = Math.min(256, extent.size_px[1] - top);
    const maxCol = Math.ceil(extent.size_px[0] / 256) - 1;
    const maxRow = Math.ceil(extent.size_px[1] / 256) - 1;
    if (!Number.isInteger(col) || !Number.isInteger(row) || col < 0 || row < 0 || col > maxCol || row > maxRow) {
      res.writeHead(400, { 'Content-Type': 'text/plain; charset=utf-8' }); res.end('Tile is outside the mosaic.'); return;
    }
    return sendImagePipeline(res, sharp(mosaicPath).extract({ left, top, width, height }).jpeg({ quality: 92 }));
  }
  if (url.pathname === '/api/model') return sendFile(res, modelPath, undefined, req.method);
  if (url.pathname.startsWith('/node_modules/')) {
    const file = path.resolve(appDir, `.${decodeURIComponent(url.pathname)}`);
    if (!file.startsWith(path.join(appDir, 'node_modules') + path.sep)) {
      res.writeHead(403); res.end(); return;
    }
    return sendFile(res, file);
  }
  const relative = decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname);
  const file = path.resolve(appDir, `.${relative}`);
  if (!file.startsWith(appDir + path.sep)) { res.writeHead(403); res.end(); return; }
  sendFile(res, file);
});

const port = Number(process.env.PORT || 8765);
server.listen(port, '127.0.0.1', () => {
  console.log(`Building Detector ready at http://127.0.0.1:${port}`);
  console.log('Keep this window open while using the browser app.');
  if (process.platform === 'win32' && process.env.BUILDING_DETECTOR_NO_BROWSER !== '1') {
    execFile('cmd.exe', ['/c', 'start', '', `http://127.0.0.1:${port}`], { windowsHide: true });
  }
});
