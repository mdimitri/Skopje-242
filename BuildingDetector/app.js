const $ = (id) => document.getElementById(id);
const overview = $('overview');
const overviewCtx = overview.getContext('2d');
const map = $('map');
const mapCtx = map.getContext('2d');
const tileCanvas = document.createElement('canvas');
tileCanvas.width = tileCanvas.height = 256;
const tileCtx = tileCanvas.getContext('2d', { willReadFrequently: true });

const statusEl = $('status');
const mapMessage = $('mapMessage');
const tileCols = $('col');
const tileRows = $('row');
const DEFAULT_THRESHOLD = 0.4371;
const mean = [0.4297, 0.4002, 0.3433];
const std = [0.2056, 0.1674, 0.1599];
let extent;
let overviewImage;
let buildings = [];
let scene;
let selectedCol = 0;
let selectedRow = 0;
let modelSession;
let modelReady = false;
let modelPixels = null;
let modelConfidence = null;
let components = [];
let currentBitmap;
let tileOsms = [];
let osmOpacity = 1;

function setStatus(message) { statusEl.textContent = message; }
function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }

function lonToPx(lon) { return (lon + 180) / 360 * 256 * 2 ** extent.zoom; }
function latToPx(lat) {
  const radians = lat * Math.PI / 180;
  return (1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2 * 256 * 2 ** extent.zoom;
}
function pxToLon(x) { return x / (256 * 2 ** extent.zoom) * 360 - 180; }
function pxToLat(y) { return Math.atan(Math.sinh(Math.PI * (1 - 2 * y / (256 * 2 ** extent.zoom)))) * 180 / Math.PI; }
function imagePixel(lon, lat) {
  return [lonToPx(lon) - extent.origin_global_px[0], latToPx(lat) - extent.origin_global_px[1]];
}

function drawOverview() {
  const cols = Math.ceil(extent.size_px[0] / 256);
  const rows = Math.ceil(extent.size_px[1] / 256);
  const sx = overview.width / extent.size_px[0];
  const sy = overview.height / extent.size_px[1];
  overviewCtx.fillStyle = '#273233';
  overviewCtx.fillRect(0, 0, overview.width, overview.height);
  if (overviewImage) overviewCtx.drawImage(overviewImage, 0, 0, overview.width, overview.height);
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      overviewCtx.strokeStyle = 'rgba(228, 242, 238, 0.16)';
      overviewCtx.lineWidth = 0.45;
      overviewCtx.strokeRect(col * 256 * sx, row * 256 * sy, 256 * sx, 256 * sy);
    }
  }
  overviewCtx.strokeStyle = '#9aabab';
  overviewCtx.lineWidth = 1;
  overviewCtx.strokeRect(0.5, 0.5, overview.width - 1, overview.height - 1);
  overviewCtx.fillStyle = '#80dfbd';
  overviewCtx.fillRect(selectedCol * 256 * sx, selectedRow * 256 * sy, Math.max(2, 256 * sx), Math.max(2, 256 * sy));
  overviewCtx.strokeStyle = '#ecfff8';
  overviewCtx.lineWidth = 2;
  overviewCtx.strokeRect(selectedCol * 256 * sx + 1, selectedRow * 256 * sy + 1, 256 * sx - 2, 256 * sy - 2);
}

function formatCoordinate(lon, lat) { return `${lat.toFixed(5)}°, ${lon.toFixed(5)}°`; }

function makeProjectedBuildings(elements) {
  const projected = [];
  for (const feature of elements) {
    if (!feature.geometry || feature.geometry.length < 3) continue;
    const points = [];
    for (const coordinate of feature.geometry) {
      if (!Number.isFinite(coordinate.lat) || !Number.isFinite(coordinate.lon)) continue;
      points.push(imagePixel(coordinate.lon, coordinate.lat));
    }
    if (points.length < 3) continue;
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    projected.push({ id: `${feature.type}/${feature.id}`, points, minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys), tags: feature.tags || {} });
  }
  return projected;
}

function updateTileInputs() {
  const maxCol = Math.ceil(extent.size_px[0] / 256) - 1;
  const maxRow = Math.ceil(extent.size_px[1] / 256) - 1;
  selectedCol = clamp(Math.floor(selectedCol), 0, maxCol);
  selectedRow = clamp(Math.floor(selectedRow), 0, maxRow);
  tileCols.value = selectedCol;
  tileRows.value = selectedRow;
  $('tileLabel').textContent = `Tile ${selectedCol}, ${selectedRow}`;
  $('tileTitle').textContent = `Web Mercator tile ${selectedCol}, ${selectedRow}`;
  const centerX = extent.origin_global_px[0] + selectedCol * 256 + 128;
  const centerY = extent.origin_global_px[1] + selectedRow * 256 + 128;
  const center = formatCoordinate(pxToLon(centerX), pxToLat(centerY));
  $('coords').textContent = `${center} · zoom ${extent.zoom}`;
  drawOverview();
}

function drawOsmOutline(feature, color, lineWidth = 1.6) {
  const ox = selectedCol * 256;
  const oy = selectedRow * 256;
  mapCtx.beginPath();
  for (let i = 0; i < feature.points.length; i++) {
    const [x, y] = feature.points[i];
    if (i === 0) mapCtx.moveTo(x - ox, y - oy);
    else mapCtx.lineTo(x - ox, y - oy);
  }
  mapCtx.closePath();
  mapCtx.strokeStyle = color;
  mapCtx.lineWidth = lineWidth;
  mapCtx.stroke();
}

function closeCurrentBitmap() {
  if (currentBitmap) currentBitmap.close();
  currentBitmap = null;
}

async function drawTile() {
  closeCurrentBitmap();
  const tileKey = `${selectedCol},${selectedRow}`;
  const sx = selectedCol * 256;
  const sy = selectedRow * 256;
  const width = Math.min(256, extent.size_px[0] - sx);
  const height = Math.min(256, extent.size_px[1] - sy);
  tileCtx.clearRect(0, 0, 256, 256);
  if (width > 0 && height > 0) {
    const response = await fetch(`/api/tile?col=${selectedCol}&row=${selectedRow}`);
    if (!response.ok) throw new Error('Could not crop the selected satellite tile.');
    const blob = await response.blob();
    const bitmap = await createImageBitmap(blob);
    if (tileKey !== `${selectedCol},${selectedRow}`) { bitmap.close(); return; }
    currentBitmap = bitmap;
    tileCtx.drawImage(currentBitmap, 0, 0);
    if (width < 256) {
      const strip = tileCtx.createImageData(256 - width, height);
      const edge = tileCtx.getImageData(width - 1, 0, 1, height).data;
      for (let y = 0; y < height; y++) for (let x = 0; x < 256 - width; x++) strip.data.set(edge.subarray(y * 4, y * 4 + 4), (y * (256 - width) + x) * 4);
      tileCtx.putImageData(strip, width, 0);
    }
    if (height < 256) {
      const strip = tileCtx.createImageData(256, 256 - height);
      const edge = tileCtx.getImageData(0, height - 1, 256, 1).data;
      for (let y = 0; y < 256 - height; y++) strip.data.set(edge, y * 256 * 4);
      tileCtx.putImageData(strip, 0, height);
    }
  }
  mapCtx.clearRect(0, 0, 256, 256);
  mapCtx.drawImage(tileCanvas, 0, 0);
  const left = selectedCol * 256;
  const top = selectedRow * 256;
  const right = left + width;
  const bottom = top + height;
  tileOsms = buildings.filter((f) => f.maxX >= left && f.minX <= right && f.maxY >= top && f.minY <= bottom);
  for (const feature of tileOsms) drawOsmOutline(feature, modelPixels ? '#ff646b' : '#e8f3f0');
  if (modelPixels) drawModelOverlay();
  $('summary').textContent = modelPixels ? `${tileOsms.length} OSM · ${components.length} AI` : `${tileOsms.length} OSM footprints · run model to compare`;
  $('mapMessage').classList.add('hidden');
}

function drawModelOverlay() {
  const pairs = [];
  for (let fi = 0; fi < tileOsms.length; fi++) {
    const feature = tileOsms[fi];
    const x0 = clamp(Math.floor(feature.minX - selectedCol * 256), 0, 255);
    const x1 = clamp(Math.ceil(feature.maxX - selectedCol * 256), 0, 255);
    const y0 = clamp(Math.floor(feature.minY - selectedRow * 256), 0, 255);
    const y1 = clamp(Math.ceil(feature.maxY - selectedRow * 256), 0, 255);
    let area = 0;
    const overlap = new Map();
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        if (!insidePolygon(x + 0.5 + selectedCol * 256, y + 0.5 + selectedRow * 256, feature.points)) continue;
        const at = y * 256 + x;
        area++;
        const label = modelPixels[at];
        if (label) overlap.set(label, (overlap.get(label) || 0) + 1);
      }
    }
    if (!area) continue;
    for (const [label, intersection] of overlap) {
      const detArea = components.find((component) => component.id === label)?.area || 0;
      const iou = intersection / (area + detArea - intersection);
      if (iou > 0) pairs.push({ fi, label, iou });
    }
  }

  pairs.sort((a, b) => b.iou - a.iou);
  const matchedOsm = new Map();
  const matchedDetections = new Set();
  for (const pair of pairs) {
    if (pair.iou < 0.25) break;
    if (matchedOsm.has(pair.fi) || matchedDetections.has(pair.label)) continue;
    matchedOsm.set(pair.fi, pair);
    matchedDetections.add(pair.label);
  }

  mapCtx.save();
  mapCtx.globalAlpha = osmOpacity;
  for (let fi = 0; fi < tileOsms.length; fi++) {
    const match = matchedOsm.get(fi);
    const iou = match?.iou || 0;
    const color = iou >= 0.5 ? '#58ed9c' : iou >= 0.25 ? '#f5d74e' : '#ff5d66';
    drawOsmOutline(tileOsms[fi], color, 1.65);
  }
  mapCtx.restore();

  mapCtx.save();
  const ox = selectedCol * 256;
  const oy = selectedRow * 256;
  for (const component of components) {
    const color = matchedDetections.has(component.id) ? '#efffff' : '#41d9ff';
    mapCtx.strokeStyle = color;
    mapCtx.globalAlpha = 0.35 + component.confidence * 0.65;
    mapCtx.lineWidth = 1.7;
    mapCtx.setLineDash(matchedDetections.has(component.id) ? [1.5, 1] : []);
    mapCtx.beginPath();
    for (let y = component.minY; y <= component.maxY; y++) {
      for (let x = component.minX; x <= component.maxX; x++) {
        const at = y * 256 + x;
        if (modelPixels[at] !== component.id) continue;
        if (y === 0 || modelPixels[at - 256] !== component.id) { mapCtx.moveTo(x - ox, y - oy); mapCtx.lineTo(x + 1 - ox, y - oy); }
        if (x === 255 || modelPixels[at + 1] !== component.id) { mapCtx.moveTo(x + 1 - ox, y - oy); mapCtx.lineTo(x + 1 - ox, y + 1 - oy); }
        if (y === 255 || modelPixels[at + 256] !== component.id) { mapCtx.moveTo(x + 1 - ox, y + 1 - oy); mapCtx.lineTo(x - ox, y + 1 - oy); }
        if (x === 0 || modelPixels[at - 1] !== component.id) { mapCtx.moveTo(x - ox, y + 1 - oy); mapCtx.lineTo(x - ox, y - oy); }
      }
    }
    mapCtx.stroke();
  }
  mapCtx.setLineDash([]);
  mapCtx.restore();

  const matched = matchedOsm.size;
  const unmatchedAi = components.length - matchedDetections.size;
  $('summary').textContent = `${tileOsms.length} OSM · ${matched} matched · ${tileOsms.length - matched} OSM missed · ${components.length} AI (${unmatchedAi} extra)`;
}

function insidePolygon(x, y, points) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const xi = points[i][0], yi = points[i][1];
    const xj = points[j][0], yj = points[j][1];
    const crosses = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / ((yj - yi) || 1e-12) + xi);
    if (crosses) inside = !inside;
  }
  return inside;
}

function classifyComponents() {
  const threshold = Number($('confidence').value);
  const minArea = Number($('minArea').value);
  const labels = new Uint32Array(256 * 256);
  const stats = [];
  const stack = new Int32Array(256 * 256);
  let nextId = 0;
  for (let start = 0; start < modelConfidence.length; start++) {
    if (labels[start] || modelConfidence[start] < threshold) continue;
    nextId++;
    let top = 0, area = 0;
    stack[top++] = start;
    labels[start] = nextId;
    let minX = 255, minY = 255, maxX = 0, maxY = 0, confidenceTotal = 0;
    while (top) {
      const at = stack[--top];
      const x = at % 256, y = (at / 256) | 0;
      area++;
      confidenceTotal += modelConfidence[at];
      minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
      const y0 = Math.max(0, y - 1), y1 = Math.min(255, y + 1);
      const x0 = Math.max(0, x - 1), x1 = Math.min(255, x + 1);
      for (let yy = y0; yy <= y1; yy++) {
        for (let xx = x0; xx <= x1; xx++) {
          const neighbor = yy * 256 + xx;
          if (!labels[neighbor] && modelConfidence[neighbor] >= threshold) {
            labels[neighbor] = nextId;
            stack[top++] = neighbor;
          }
        }
      }
    }
    if (area >= minArea) stats.push({ id: nextId, area, minX, minY, maxX, maxY, confidence: confidenceTotal / area });
  }
  const keep = new Set(stats.map((s) => s.id));
  for (let i = 0; i < labels.length; i++) if (!keep.has(labels[i])) labels[i] = 0;
  modelPixels = labels;
  components = stats;
}

function sigmoid(value) { return 1 / (1 + Math.exp(-value)); }

async function runModel() {
  const runTileKey = `${selectedCol},${selectedRow}`;
  $('runModel').disabled = true;
  setStatus('Preparing model input…');
  $('mapMessage').textContent = 'Running AI segmentation on this tile…';
  $('mapMessage').classList.remove('hidden');
  try {
    if (!modelSession) {
      setStatus('Loading 210 MB HOTOSM model…');
      ort.env.wasm.numThreads = 1;
      ort.env.wasm.wasmPaths = '/node_modules/onnxruntime-web/dist/';
      modelSession = await ort.InferenceSession.create('/api/model', { executionProviders: ['wasm'], graphOptimizationLevel: 'all' });
    }
    const rgba = tileCtx.getImageData(0, 0, 256, 256).data;
    const input = new Float32Array(3 * 256 * 256);
    for (let i = 0; i < 256 * 256; i++) {
      input[i] = (rgba[i * 4] / 255 - mean[0]) / std[0];
      input[256 * 256 + i] = (rgba[i * 4 + 1] / 255 - mean[1]) / std[1];
      input[2 * 256 * 256 + i] = (rgba[i * 4 + 2] / 255 - mean[2]) / std[2];
    }
    const tensor = new ort.Tensor('float32', input, [1, 3, 256, 256]);
    setStatus('Segmenting selected tile…');
    const output = await modelSession.run({ [modelSession.inputNames[0]]: tensor });
    if (runTileKey !== `${selectedCol},${selectedRow}`) return;
    const outputTensor = output[modelSession.outputNames[0]];
    const channelCount = outputTensor.dims.length === 4 ? outputTensor.dims[1] : 1;
    if (outputTensor.data.length < 256 * 256) throw new Error('Model returned an unexpected output shape.');
    modelConfidence = new Float32Array(256 * 256);
    for (let i = 0; i < modelConfidence.length; i++) modelConfidence[i] = sigmoid(outputTensor.data[i]);
    classifyComponents();
    $('mapMessage').classList.add('hidden');
    mapCtx.drawImage(tileCanvas, 0, 0);
    drawModelOverlay();
    const channelNote = channelCount > 1 ? '' : ' (single output channel)';
    setStatus(`DINOv3-S complete${channelNote}. Adjust confidence to review candidate outlines.`);
  } catch (error) {
    $('mapMessage').classList.add('hidden');
    setStatus(`Model error: ${error.message}`);
    console.error(error);
  } finally {
    $('runModel').disabled = !modelReady;
    if (runTileKey !== `${selectedCol},${selectedRow}`) setStatus(`Tile ${selectedCol}, ${selectedRow} selected. Run the model to compare it.`);
  }
}

function onConfidenceChange() {
  $('confidenceOut').textContent = Number($('confidence').value).toFixed(2);
  if (!modelConfidence) return;
  classifyComponents();
  mapCtx.drawImage(tileCanvas, 0, 0);
  drawModelOverlay();
}

function setOpacity() {
  osmOpacity = Number($('opacity').value) / 100;
  $('opacityOut').textContent = `${Math.round(osmOpacity * 100)}%`;
  if (modelConfidence) {
    mapCtx.drawImage(tileCanvas, 0, 0);
    drawModelOverlay();
  }
}

async function load() {
  try {
    const [extentResponse, buildingsResponse] = await Promise.all([fetch('/api/extent'), fetch('/api/buildings')]);
    if (!extentResponse.ok || !buildingsResponse.ok) throw new Error('The satellite extent or OSM buildings.json could not be loaded.');
    extent = await extentResponse.json();
    setStatus('Reading downloaded OSM building footprints…');
    const osm = await buildingsResponse.json();
    buildings = makeProjectedBuildings(osm.elements || []);
    setStatus('Preparing satellite overview…');
    const [overviewResponse, modelCheck] = await Promise.all([fetch('/api/overview'), fetch('/api/model', { method: 'HEAD' })]);
    if (!overviewResponse.ok) throw new Error('Could not create a mosaic overview from the satellite image.');
    overviewImage = await createImageBitmap(await overviewResponse.blob());
    modelReady = modelCheck.ok && typeof ort !== 'undefined';
    $('runModel').disabled = !modelReady;
    if (!modelReady) setStatus('Run setup.bat to install ONNX Runtime Web and download the AI model.');
    updateTileInputs();
    await drawTile();
    if (modelReady) setStatus(`Ready · ${buildings.length.toLocaleString()} OSM building outlines indexed`);
  } catch (error) {
    setStatus(error.message);
    mapMessage.textContent = error.message;
    console.error(error);
  }
}

function selectTile(col, row) {
  selectedCol = col;
  selectedRow = row;
  modelPixels = null;
  modelConfidence = null;
  components = [];
  updateTileInputs();
  $('summary').textContent = 'No model run yet';
  if (extent) drawTile().catch((error) => setStatus(error.message));
}

overview.addEventListener('click', (event) => {
  const rect = overview.getBoundingClientRect();
  const x = (event.clientX - rect.left) / rect.width * extent.size_px[0];
  const y = (event.clientY - rect.top) / rect.height * extent.size_px[1];
  selectTile(Math.floor(x / 256), Math.floor(y / 256));
});
tileCols.addEventListener('change', () => selectTile(Number(tileCols.value), selectedRow));
tileRows.addEventListener('change', () => selectTile(selectedCol, Number(tileRows.value)));
$('previous').addEventListener('click', () => selectTile(selectedCol > 0 ? selectedCol - 1 : selectedCol, selectedRow));
$('next').addEventListener('click', () => {
  const maxCol = Math.ceil(extent.size_px[0] / 256) - 1;
  selectTile(selectedCol < maxCol ? selectedCol + 1 : selectedCol, selectedRow);
});
$('runModel').addEventListener('click', runModel);
$('confidence').addEventListener('input', onConfidenceChange);
$('minArea').addEventListener('input', () => {
  $('areaOut').textContent = `${$('minArea').value} px`;
  if (!modelConfidence) return;
  classifyComponents();
  mapCtx.drawImage(tileCanvas, 0, 0);
  drawModelOverlay();
});
$('opacity').addEventListener('input', setOpacity);

load();
