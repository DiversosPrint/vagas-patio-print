const http = require('http');
const fs = require('fs');
const path = require('path');
const iconv = require('iconv-lite');
const Database = require('better-sqlite3');
const { Pool } = require('pg');

const ROOT = __dirname;
const PUBLIC = path.join(ROOT, 'public');
const VEHICLE_SHEET = process.env.PATIO_VEICULOS_PATH || path.join(ROOT, 'data', 'veiculos.xls');
const SOURCE_DB = process.env.PATIO_DB_PATH || path.join(ROOT, 'database', 'patio.db');
const APP_DB = process.env.VAGAS_PATIO_DB_PATH || path.join(ROOT, 'vagas_patio.db');
const PORT = Number(process.env.PORT || process.env.VAGAS_PATIO_PORT || 8787);
const HOST = process.env.HOST || '0.0.0.0';
const DATABASE_URL = (process.env.DATABASE_URL || '').trim();

const SLOTS = [
  ['borracharia-01', '01', 'Borracharia', 70, 30.5, 1], ['borracharia-02', '02', 'Borracharia', 70, 35, 1],
  ['centro-dir-03', '03', 'Centro (Direita)', 70, 39.5, 0], ['centro-dir-04', '04', 'Centro (Direita)', 70, 44.2, 0],
  ['centro-dir-05', '05', 'Centro (Direita)', 70, 48.8, 0], ['centro-dir-06', '06', 'Centro (Direita)', 70, 53.5, 0],
  ['centro-esq-03', '03-E', 'Centro (Esquerda)', 53.5, 44.2, 0], ['centro-esq-04', '04-E', 'Centro (Esquerda)', 53.5, 49, 0],
  ['centro-esq-05', '05-E', 'Centro (Esquerda)', 53.5, 53.8, 0], ['centro-esq-06', '06-E', 'Centro (Esquerda)', 53.5, 58.5, 0]
].map(([id, code, zone, x, y, is_borracharia]) => ({ id, code, zone, x, y, is_borracharia }));
for (let i = 1; i <= 19; i++) SLOTS.push({ id: `inferior-${String(i).padStart(2, '0')}`, code: String(i).padStart(2, '0'), zone: 'Parte inferior', x: +(18.4 + (i - 1) * 3.18).toFixed(2), y: 75.2, is_borracharia: 0 });
for (const [zone, prefix, count, x, y, dx, dy] of [['Lateral esquerda','E',8,4.4,67,0,-6],['Parte superior','S',8,48,21,3.45,0],['Noroeste','NO',8,23,39,3.2,-3.6]]) {
  for (let i = 1; i <= count; i++) SLOTS.push({ id: `${prefix.toLowerCase()}-${String(i).padStart(2,'0')}`, code: `${prefix}-${String(i).padStart(2,'0')}`, zone, x: +(x + (i - 1) * dx).toFixed(2), y: +(y + (i - 1) * dy).toFixed(2), is_borracharia: 0 });
}

function now() { return new Date().toISOString().slice(0, 19); }
function normalizePlate(value) { return String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, ''); }
function sendJson(res, value, status = 200) { const raw = Buffer.from(JSON.stringify(value)); res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': raw.length }); res.end(raw); }
function readBody(req) { return new Promise((resolve, reject) => { let body = ''; req.on('data', chunk => body += chunk); req.on('end', () => { try { resolve(body ? JSON.parse(body) : {}); } catch (e) { reject(e); } }); req.on('error', reject); }); }

const sqlite = new Database(APP_DB);
sqlite.pragma('journal_mode = WAL');
sqlite.exec(`CREATE TABLE IF NOT EXISTS slots (id TEXT PRIMARY KEY, code TEXT NOT NULL, zone TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, is_borracharia INTEGER DEFAULT 0); CREATE TABLE IF NOT EXISTS slot_history (id INTEGER PRIMARY KEY AUTOINCREMENT, slot_id TEXT NOT NULL, mode TEXT NOT NULL, operation TEXT NOT NULL, vehicle_id INTEGER, trailer_id INTEGER, custom_plate TEXT, custom_trailer TEXT, driver TEXT, notes TEXT, vehicle_kind TEXT, entered_at TEXT NOT NULL, exited_at TEXT, created_at TEXT NOT NULL);`);
for (const col of ['custom_plate','custom_trailer','driver','notes','vehicle_kind']) { try { sqlite.exec(`ALTER TABLE slot_history ADD COLUMN ${col} TEXT`); } catch (_) {} }
try { sqlite.exec('ALTER TABLE slots ADD COLUMN is_borracharia INTEGER DEFAULT 0'); } catch (_) {}
const validIds = SLOTS.map(s => `'${s.id.replace(/'/g, "''")}'`).join(',');
sqlite.prepare(`DELETE FROM slots WHERE id NOT IN (${validIds})`).run();
const upsertSlot = sqlite.prepare('INSERT INTO slots(id,code,zone,x,y,is_borracharia) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET code=excluded.code,zone=excluded.zone,x=excluded.x,y=excluded.y,is_borracharia=excluded.is_borracharia');
const saveSlots = sqlite.transaction(() => SLOTS.forEach(s => upsertSlot.run(s.id,s.code,s.zone,s.x,s.y,s.is_borracharia)));
saveSlots();

let vehicleCache = { at: 0, rows: null };
let sheetCache = { signature: '', rows: null };
let pool = DATABASE_URL ? new Pool({ connectionString: DATABASE_URL, connectionTimeoutMillis: 10000, max: 4 }) : null;

function decodeEntities(s) { return String(s).replace(/&nbsp;/gi, ' ').replace(/&amp;/gi, '&').replace(/&quot;/gi, '"').replace(/&#39;/gi, "'").replace(/&lt;/gi, '<').replace(/&gt;/gi, '>'); }
function spreadsheetVehicleRows() {
  if (!fs.existsSync(VEHICLE_SHEET)) return [];
  const stat = fs.statSync(VEHICLE_SHEET); const signature = `${stat.mtimeMs}:${stat.size}`;
  if (sheetCache.signature === signature && sheetCache.rows) return sheetCache.rows;
  try {
    const html = iconv.decode(fs.readFileSync(VEHICLE_SHEET), 'win1252');
    const rows = [...html.matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/gi)].map(m => [...m[1].matchAll(/<(?:td|th)[^>]*>([\s\S]*?)<\/(?:td|th)>/gi)].map(c => decodeEntities(c[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim())));
    if (rows.length < 3) return [];
    const headers = rows[1].map(v => v.toUpperCase()); const index = Object.fromEntries(headers.map((v, i) => [v, i]));
    const required = ['ID','PLACA','CHASSI','MARCA','MODELO','TIPO','STATUS OPERACIONAL','STATUS PRINCIPAL']; if (required.some(k => index[k] === undefined)) return [];
    const seen = new Set(); const value = (row, key) => String(row[index[key]] || '').trim(); const result = [];
    for (const row of rows.slice(2)) { const plate = value(row,'PLACA').toUpperCase(); const key = normalizePlate(plate); if (!key || seen.has(key) || plate.includes('PLACA FICT')) continue; seen.add(key); result.push({ id: value(row,'ID') || null, plate, type: value(row,'TIPO'), yard: value(row,'UNIDADE') || value(row,'PONTO DE APOIO'), chassis: value(row,'CHASSI'), status: value(row,'STATUS OPERACIONAL') || value(row,'STATUS PRINCIPAL'), entryTime: null, exitTime: null, base: value(row,'PONTO DE APOIO'), baseDestino: value(row,'UNIDADE'), entregar_diversos: 0, entregar_correios: 0, brand: value(row,'MARCA'), model: value(row,'MODELO'), operation: value(row,'OPERAÇÃO'), statusPrincipal: value(row,'STATUS PRINCIPAL') }); }
    sheetCache = { signature, rows: result }; return result;
  } catch (e) { console.error('Falha ao ler planilha:', e.message); return []; }
}
async function postgresVehicleRows() {
  if (!pool) return [];
  try { const { rows } = await pool.query(`SELECT v.id, v.plate, v.type, v.yard, v.chassis, v.status, v.entryTime, v.exitTime, v.base, v.baseDestino, v.entregar_diversos, v.entregar_correios, c.brand, c.model FROM vehicles v LEFT JOIN vehicle_catalog c ON UPPER(v.plate)=UPPER(c.plate) WHERE COALESCE(v.status,'') <> 'Liberado' ORDER BY v.plate`); return rows; }
  catch (e) { console.error('Falha ao consultar PostgreSQL; usando fallback local:', e.message); return []; }
}
async function vehicleRows() { if (vehicleCache.rows && Date.now() - vehicleCache.at < 30000) return vehicleCache.rows; let rows = await postgresVehicleRows(); if (!rows.length) rows = spreadsheetVehicleRows(); if (!rows.length && fs.existsSync(SOURCE_DB)) { try { const source = new Database(SOURCE_DB, { readonly: true }); rows = source.prepare(`SELECT v.id,v.plate,v.type,v.yard,v.chassis,v.status,v.entryTime,v.exitTime,v.base,v.baseDestino,v.entregar_diversos,v.entregar_correios,c.brand,c.model FROM vehicles v LEFT JOIN vehicle_catalog c ON UPPER(v.plate)=UPPER(c.plate) WHERE COALESCE(v.status,'') <> 'Liberado' ORDER BY v.plate`).all(); source.close(); } catch (_) {} } vehicleCache = { at: Date.now(), rows }; return rows; }
function vehicleMap(rows) { return new Map(rows.map(v => [String(v.id), v])); }
function fallbackVehicle(plate, trailer = false) { return plate ? { id: null, plate, type: trailer ? 'Carreta' : 'Veículo cadastrado', yard: 'Pátio Jaraguá', chassis: '—' } : null; }
function enrich(item, map) { const v = (item.vehicle_id && map.get(String(item.vehicle_id))) || fallbackVehicle(item.custom_plate); const t = (item.trailer_id && map.get(String(item.trailer_id))) || fallbackVehicle(item.custom_trailer, true); return { ...item, vehicle: v, trailer: t }; }
async function enrichedSlot(slot, map) { const current = sqlite.prepare('SELECT * FROM slot_history WHERE slot_id=? AND exited_at IS NULL ORDER BY id DESC LIMIT 1').get(slot.id); const historyCount = sqlite.prepare('SELECT COUNT(*) AS count FROM slot_history WHERE slot_id=?').get(slot.id).count; return { ...slot, historyCount, current: current ? enrich(current, map) : null }; }

async function apiGet(req, res, pathname) {
  const rows = await vehicleRows();
  if (pathname === '/api/vehicles') return sendJson(res, rows);
  if (pathname === '/api/slots') { const map = vehicleMap(rows); const ordered = sqlite.prepare("SELECT * FROM slots ORDER BY CASE WHEN is_borracharia=1 THEN 0 WHEN zone LIKE 'Centro%' THEN 1 ELSE 2 END, id").all(); return sendJson(res, await Promise.all(ordered.map(s => enrichedSlot(s, map)))); }
  const history = pathname.match(/^\/api\/slots\/([^/]+)\/history$/);
  if (history) { const map = vehicleMap(rows); const list = sqlite.prepare('SELECT * FROM slot_history WHERE slot_id=? ORDER BY entered_at DESC').all(decodeURIComponent(history[1])); return sendJson(res, list.map(item => enrich(item, map))); }
  return null;
}
async function updateSlot(res, slotId, payload) {
  const mode = payload.mode || 'empty', operation = payload.operation || 'Diversos', rows = await vehicleRows(), map = vehicleMap(rows);
  const vehicleId = payload.vehicleId || null, trailerId = payload.trailerId || null, customPlate = String(payload.customPlate || '').trim().toUpperCase() || null, customTrailer = String(payload.customTrailer || '').trim().toUpperCase() || null;
  const driver = String(payload.driver || '').trim() || null, notes = String(payload.notes || '').trim() || null, vehicleKind = String(payload.vehicleKind || '').trim() || null, enteredAt = payload.enteredAt || now();
  if (mode === 'isolated' && !vehicleId && !customPlate) return sendJson(res, { error: 'Informe a placa ou selecione um veículo da lista' }, 400);
  if (mode === 'conjunto' && (!(vehicleId || customPlate) || !(trailerId || customTrailer))) return sendJson(res, { error: 'Informe o cavalo e a carreta' }, 400);
  const requestedIds = new Set([vehicleId, trailerId].filter(Boolean).map(String)); const requestedPlates = new Set([customPlate, customTrailer].filter(Boolean).map(normalizePlate));
  for (const id of requestedIds) { const plate = map.get(id)?.plate; if (plate) requestedPlates.add(normalizePlate(plate)); }
  const active = sqlite.prepare("SELECT h.*,s.code AS slot_code FROM slot_history h JOIN slots s ON s.id=h.slot_id WHERE h.exited_at IS NULL AND h.slot_id<>?").all(slotId);
  for (const item of active) { const existingIds = new Set([item.vehicle_id,item.trailer_id].filter(Boolean).map(String)); const existingPlates = new Set([item.custom_plate,item.custom_trailer].filter(Boolean).map(normalizePlate)); for (const id of existingIds) { const p = map.get(id)?.plate; if (p) existingPlates.add(normalizePlate(p)); } const duplicate = [...requestedPlates].find(p => existingPlates.has(p)); if ([...requestedIds].some(id => existingIds.has(id)) || duplicate) return sendJson(res, { error: `Esta placa já está ocupando a vaga ${item.slot_code}. Libere a vaga anterior antes de alocar novamente.`, code: 'DUPLICATE_ACTIVE_VEHICLE', slot: item.slot_code, plate: duplicate || '' }, 409); }
  const timestamp = now(); const transaction = sqlite.transaction(() => { sqlite.prepare('UPDATE slot_history SET exited_at=? WHERE slot_id=? AND exited_at IS NULL').run(timestamp, slotId); if (mode !== 'empty') sqlite.prepare('INSERT INTO slot_history(slot_id,mode,operation,vehicle_id,trailer_id,custom_plate,custom_trailer,driver,notes,vehicle_kind,entered_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)').run(slotId,mode,operation,vehicleId,trailerId,customPlate,customTrailer,driver,notes,vehicleKind,enteredAt,timestamp); });
  transaction(); return sendJson(res, { success: true });
}

function serveStatic(res, pathname) { const name = pathname === '/' ? 'index.html' : pathname === '/login' ? 'login.html' : decodeURIComponent(pathname.slice(1)); const file = path.resolve(PUBLIC, name); if (!file.startsWith(path.resolve(PUBLIC)) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return sendJson(res, { error: 'Arquivo não encontrado' }, 404); const ext = path.extname(file).toLowerCase(); const types = { '.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'application/javascript; charset=utf-8','.json':'application/json; charset=utf-8','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.svg':'image/svg+xml','.webmanifest':'application/manifest+json; charset=utf-8' }; res.writeHead(200, { 'Content-Type': types[ext] || 'application/octet-stream', ...(path.basename(file) === 'sw.js' ? { 'Service-Worker-Allowed':'/', 'Cache-Control':'no-cache, no-store, must-revalidate' } : {}) }); fs.createReadStream(file).pipe(res); }

const server = http.createServer(async (req, res) => { try { const parsed = new URL(req.url, `http://${req.headers.host || 'localhost'}`); const pathname = parsed.pathname; if (req.method === 'GET' && pathname.startsWith('/api/')) { const result = await apiGet(req, res, pathname); if (result === null) return sendJson(res, { error: 'Rota não encontrada' }, 404); return; } const slot = pathname.match(/^\/api\/slots\/([^/]+)$/); if (req.method === 'PUT' && slot) return updateSlot(res, decodeURIComponent(slot[1]), await readBody(req)); const position = pathname.match(/^\/api\/slots\/([^/]+)\/position$/); if (req.method === 'POST' && position) { const body = await readBody(req); sqlite.prepare('UPDATE slots SET x=?, y=? WHERE id=?').run(Number(body.x || 0), Number(body.y || 0), decodeURIComponent(position[1])); return sendJson(res, { success: true, x: Number(body.x || 0), y: Number(body.y || 0) }); } if (req.method === 'GET') return serveStatic(res, pathname); sendJson(res, { error: 'Método não suportado' }, 405); } catch (e) { console.error(e); sendJson(res, { error: 'Erro interno do servidor' }, 500); } });
server.listen(PORT, HOST, () => console.log(`Sistema Vagas Pátio Jaraguá: http://${HOST}:${PORT}`));
process.on('SIGTERM', () => { sqlite.close(); if (pool) pool.end(); server.close(() => process.exit(0)); });
