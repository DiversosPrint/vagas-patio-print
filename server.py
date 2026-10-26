import json
import os
import sqlite3
import re
import time
from html import unescape
from html.parser import HTMLParser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / 'public'
SOURCE_DB = Path(os.environ.get('PATIO_DB_PATH', r'C:\Users\Pixel Midia 3D\controle-patio-print\database\patio.db'))
VEHICLE_SHEET = Path(os.environ.get('PATIO_VEICULOS_PATH', str(ROOT / 'data' / 'veiculos.xls')))
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
APP_DB = Path(os.environ['VAGAS_PATIO_DB_PATH']) if os.environ.get('VAGAS_PATIO_DB_PATH') else SOURCE_DB.parent / 'vagas_patio.db'
PORT = int(os.environ.get('PORT', os.environ.get('VAGAS_PATIO_PORT', '8787')))
HOST = os.environ.get('HOST', '0.0.0.0')
VEHICLE_CACHE = {'at': 0.0, 'rows': None}
SHEET_CACHE = {'signature': None, 'rows': None}

SLOTS = [
    # 1. BORRACHARIA (Vagas 01 e 02) — Baias em frente à oficina
    {'id': 'borracharia-01', 'code': '01', 'zone': 'Borracharia', 'x': 70.0, 'y': 30.5, 'is_borracharia': 1},
    {'id': 'borracharia-02', 'code': '02', 'zone': 'Borracharia', 'x': 70.0, 'y': 35.0, 'is_borracharia': 1},

    # 2. ÁREA CENTRAL - DIREITA (Vagas 03 a 06)
    {'id': 'centro-dir-03', 'code': '03', 'zone': 'Centro (Direita)', 'x': 70.0, 'y': 39.5, 'is_borracharia': 0},
    {'id': 'centro-dir-04', 'code': '04', 'zone': 'Centro (Direita)', 'x': 70.0, 'y': 44.2, 'is_borracharia': 0},
    {'id': 'centro-dir-05', 'code': '05', 'zone': 'Centro (Direita)', 'x': 70.0, 'y': 48.8, 'is_borracharia': 0},
    {'id': 'centro-dir-06', 'code': '06', 'zone': 'Centro (Direita)', 'x': 70.0, 'y': 53.5, 'is_borracharia': 0},

    # 3. ÁREA CENTRAL - ESQUERDA (Vagas 03-E a 06-E)
    {'id': 'centro-esq-03', 'code': '03-E', 'zone': 'Centro (Esquerda)', 'x': 53.5, 'y': 44.2, 'is_borracharia': 0},
    {'id': 'centro-esq-04', 'code': '04-E', 'zone': 'Centro (Esquerda)', 'x': 53.5, 'y': 49.0, 'is_borracharia': 0},
    {'id': 'centro-esq-05', 'code': '05-E', 'zone': 'Centro (Esquerda)', 'x': 53.5, 'y': 53.8, 'is_borracharia': 0},
    {'id': 'centro-esq-06', 'code': '06-E', 'zone': 'Centro (Esquerda)', 'x': 53.5, 'y': 58.5, 'is_borracharia': 0},
]

# 4. PARTE INFERIOR (19 vagas — Exatamente como era antes)
for i in range(1, 20):
    SLOTS.append({
        'id': f'inferior-{i:02d}',
        'code': f'{i:02d}',
        'zone': 'Parte inferior',
        'x': round(18.4 + (i - 1) * 3.18, 2),
        'y': 75.2,
        'is_borracharia': 0
    })

# 5. DEMAIS ZONAS ORIGINAIS (Lateral esquerda, Parte superior, Noroeste)
for group, prefix, count, x, y, dx, dy in [
    ('Lateral esquerda', 'E', 8, 4.4, 67, 0, -6),
    ('Parte superior', 'S', 8, 48, 21, 3.45, 0),
    ('Noroeste', 'NO', 8, 23, 39, 3.2, -3.6),
]:
    for i in range(1, count + 1):
        SLOTS.append({
            'id': f'{prefix.lower()}-{i:02d}',
            'code': f'{prefix}-{i:02d}',
            'zone': group,
            'x': round(x + (i - 1) * dx, 2),
            'y': round(y + (i - 1) * dy, 2),
            'is_borracharia': 0
        })

def now(): return datetime.now().isoformat(timespec='seconds')
def db(path, read_only=False):
    uri = f'file:{path.as_posix()}?mode=ro' if read_only else str(path)
    conn = sqlite3.connect(uri, uri=read_only, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    global APP_DB
    try:
        conn = db(APP_DB)
    except sqlite3.OperationalError:
        APP_DB = Path.home() / '.vagas_patio' / 'vagas_patio.db'
        APP_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = db(APP_DB)
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS slots (
        id TEXT PRIMARY KEY,
        code TEXT NOT NULL,
        zone TEXT NOT NULL,
        x REAL NOT NULL,
        y REAL NOT NULL,
        is_borracharia INTEGER DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS slot_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slot_id TEXT NOT NULL,
        mode TEXT NOT NULL,
        operation TEXT NOT NULL,
        vehicle_id INTEGER,
        trailer_id INTEGER,
        custom_plate TEXT,
        custom_trailer TEXT,
        driver TEXT,
        notes TEXT,
        vehicle_kind TEXT,
        entered_at TEXT NOT NULL,
        exited_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(slot_id) REFERENCES slots(id)
      );
    ''')
    for col in ['custom_plate', 'custom_trailer', 'driver', 'notes', 'vehicle_kind']:
        try: conn.execute(f'ALTER TABLE slot_history ADD COLUMN {col} TEXT')
        except sqlite3.OperationalError: pass
    try: conn.execute('ALTER TABLE slots ADD COLUMN is_borracharia INTEGER DEFAULT 0')
    except sqlite3.OperationalError: pass

    # Remove códigos obsoletos e IDs duplicados para manter apenas as vagas ativas
    valid_ids = [s['id'] for s in SLOTS]
    placeholders = ','.join('?' for _ in valid_ids)
    conn.execute(f"DELETE FROM slots WHERE id NOT IN ({placeholders})", valid_ids)

    for slot in SLOTS:
        conn.execute('''
            INSERT INTO slots(id, code, zone, x, y, is_borracharia)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                code = excluded.code,
                zone = excluded.zone,
                x = excluded.x,
                y = excluded.y,
                is_borracharia = excluded.is_borracharia
        ''', (slot['id'], slot['code'], slot['zone'], slot['x'], slot['y'], slot.get('is_borracharia', 0)))
    conn.commit()
    conn.close()

def vehicle_rows():
    if VEHICLE_CACHE['rows'] is not None and time.monotonic() - VEHICLE_CACHE['at'] < 30:
        return VEHICLE_CACHE['rows']
    rows = []
    if DATABASE_URL:
        rows = postgres_vehicle_rows()
    if not rows:
        rows = spreadsheet_vehicle_rows()
    if not rows and SOURCE_DB.exists():
        conn = db(SOURCE_DB, True)
        rows = [dict(r) for r in conn.execute("""
            SELECT v.id, v.plate, v.type, v.yard, v.chassis, v.status, v.entryTime, v.exitTime, v.base, v.baseDestino,
                   v.entregar_diversos, v.entregar_correios,
                   c.brand, c.model
            FROM vehicles v
            LEFT JOIN vehicle_catalog c ON UPPER(v.plate) = UPPER(c.plate)
            WHERE COALESCE(v.status,'') <> 'Liberado'
            ORDER BY v.plate
        """).fetchall()]
        conn.close()
    VEHICLE_CACHE.update({'at': time.monotonic(), 'rows': rows})
    return rows

def postgres_vehicle_rows():
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10) as conn:
            rows = conn.execute("""
                SELECT v.id, v.plate, v.type, v.yard, v.chassis, v.status, v.entryTime, v.exitTime, v.base, v.baseDestino,
                       v.entregar_diversos, v.entregar_correios,
                       c.brand, c.model
                FROM vehicles v
                LEFT JOIN vehicle_catalog c ON UPPER(v.plate) = UPPER(c.plate)
                WHERE COALESCE(v.status,'') <> 'Liberado'
                ORDER BY v.plate
            """).fetchall()
            return [dict(row) for row in rows]
    except Exception as exc:
        print(f'Falha ao consultar PostgreSQL; usando fallback local: {exc}')
        return []

def vehicle_map(): return {str(v['id']): v for v in vehicle_rows()}

def normalize_plate(value):
    return ''.join(ch for ch in str(value or '').upper() if ch.isalnum())

class HtmlSpreadsheetParser(HTMLParser):
    """Lê o .xls exportado como tabela HTML, sem depender do Excel no servidor."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []
            self.text = []

    def handle_data(self, data):
        if self.cell is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            value = unescape(''.join(self.text)).replace('\xa0', ' ').strip()
            self.row.append(re.sub(r'\s+', ' ', value))
            self.cell = None
            self.text = []
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None

def spreadsheet_vehicle_rows():
    if not VEHICLE_SHEET.exists():
        return []
    try:
        signature = (VEHICLE_SHEET.stat().st_mtime_ns, VEHICLE_SHEET.stat().st_size)
        if SHEET_CACHE['signature'] == signature and SHEET_CACHE['rows'] is not None:
            return SHEET_CACHE['rows']
        parser = HtmlSpreadsheetParser()
        parser.feed(VEHICLE_SHEET.read_bytes().decode('cp1252', errors='replace'))
        if len(parser.rows) < 3:
            return []

        headers = [str(v).upper() for v in parser.rows[1]]
        index = {name: i for i, name in enumerate(headers)}
        required = ['ID', 'PLACA', 'CHASSI', 'MARCA', 'MODELO', 'TIPO', 'STATUS OPERACIONAL', 'STATUS PRINCIPAL']
        if any(name not in index for name in required):
            return []

        def value(row, name):
            pos = index.get(name)
            return row[pos].strip() if pos is not None and pos < len(row) and row[pos] else ''

        result = []
        seen = set()
        for row in parser.rows[2:]:
            plate = value(row, 'PLACA').upper()
            key = normalize_plate(plate)
            if not key or key in seen or 'PLACA FICT' in plate:
                continue
            seen.add(key)
            result.append({
                'id': value(row, 'ID') or None,
                'plate': plate,
                'type': value(row, 'TIPO'),
                'yard': value(row, 'UNIDADE') or value(row, 'PONTO DE APOIO'),
                'chassis': value(row, 'CHASSI'),
                'status': value(row, 'STATUS OPERACIONAL') or value(row, 'STATUS PRINCIPAL'),
                'entryTime': None,
                'exitTime': None,
                'base': value(row, 'PONTO DE APOIO'),
                'baseDestino': value(row, 'UNIDADE'),
                'entregar_diversos': 0,
                'entregar_correios': 0,
                'brand': value(row, 'MARCA'),
                'model': value(row, 'MODELO'),
                'operation': value(row, 'OPERAÇÃO'),
                'statusPrincipal': value(row, 'STATUS PRINCIPAL')
            })
        SHEET_CACHE.update({'signature': signature, 'rows': result})
        return result
    except Exception as exc:
        print(f'Falha ao ler planilha de veículos: {exc}')
        return []

def enriched_slot(slot, vehicles):
    conn = db(APP_DB, True)
    current = conn.execute('SELECT * FROM slot_history WHERE slot_id=? AND exited_at IS NULL ORDER BY id DESC LIMIT 1', (slot['id'],)).fetchone()
    count = conn.execute('SELECT COUNT(*) FROM slot_history WHERE slot_id=?', (slot['id'],)).fetchone()[0]
    conn.close()
    result = dict(slot)
    result['historyCount'] = count
    result['current'] = None
    if current:
        item = dict(current)
        v = vehicles.get(str(item.get('vehicle_id'))) if item.get('vehicle_id') else None
        t = vehicles.get(str(item.get('trailer_id'))) if item.get('trailer_id') else None
        if not v and item.get('custom_plate'):
            v = {'id': None, 'plate': item['custom_plate'], 'type': 'Veículo cadastrado', 'yard': 'Pátio Jaraguá', 'chassis': '—'}
            if SOURCE_DB.exists():
                try:
                    sconn = db(SOURCE_DB, True)
                    cat = sconn.execute('SELECT brand, model, type FROM vehicle_catalog WHERE UPPER(plate)=?', (item['custom_plate'].upper(),)).fetchone()
                    sconn.close()
                    if cat:
                        v['brand'] = cat['brand']
                        v['model'] = cat['model']
                        if cat['type']: v['type'] = cat['type']
                except Exception: pass
        if not t and item.get('custom_trailer'):
            t = {'id': None, 'plate': item['custom_trailer'], 'type': 'Carreta', 'yard': 'Pátio Jaraguá', 'chassis': '—'}
            if SOURCE_DB.exists():
                try:
                    sconn = db(SOURCE_DB, True)
                    cat = sconn.execute('SELECT brand, model, type FROM vehicle_catalog WHERE UPPER(plate)=?', (item['custom_trailer'].upper(),)).fetchone()
                    sconn.close()
                    if cat:
                        t['brand'] = cat['brand']
                        t['model'] = cat['model']
                        if cat['type']: t['type'] = cat['type']
                except Exception: pass
        item['vehicle'] = v
        item['trailer'] = t
        result['current'] = item
    return result

class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        length = int(self.headers.get('Content-Length', '0'))
        return json.loads(self.rfile.read(length) or '{}')

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == '/api/vehicles': return self.send_json(vehicle_rows())
        if url.path == '/api/slots':
            vehicles = vehicle_map()
            conn = db(APP_DB, True)
            rows = [dict(r) for r in conn.execute('SELECT * FROM slots ORDER BY CASE WHEN is_borracharia=1 THEN 0 WHEN zone LIKE \'Centro%\' THEN 1 ELSE 2 END, id')]
            conn.close()
            return self.send_json([enriched_slot(s, vehicles) for s in rows])
        if url.path.startswith('/api/slots/') and url.path.endswith('/history'):
            slot_id = url.path.split('/')[3]
            vehicles = vehicle_map()
            conn = db(APP_DB, True)
            rows = [dict(r) for r in conn.execute('SELECT * FROM slot_history WHERE slot_id=? ORDER BY entered_at DESC', (slot_id,))]
            conn.close()
            res = []
            for r in rows:
                item = dict(r)
                v = vehicles.get(str(item.get('vehicle_id'))) if item.get('vehicle_id') else None
                t = vehicles.get(str(item.get('trailer_id'))) if item.get('trailer_id') else None
                if not v and item.get('custom_plate'):
                    v = {'id': None, 'plate': item['custom_plate'], 'type': 'Veículo cadastrado', 'yard': 'Pátio Jaraguá'}
                if not t and item.get('custom_trailer'):
                    t = {'id': None, 'plate': item['custom_trailer'], 'type': 'Carreta', 'yard': 'Pátio Jaraguá'}
                item['vehicle'] = v
                item['trailer'] = t
                res.append(item)
            return self.send_json(res)
        if url.path in ('/', '/index.html'): return self.static('index.html')
        if url.path in ('/login', '/login.html'): return self.static('login.html')
        decoded_path = unquote(url.path.lstrip('/'))
        return self.static(decoded_path)

    def do_PUT(self):
        url = urlparse(self.path)
        if not url.path.startswith('/api/slots/'):
            return self.send_json({'error': 'Rota não encontrada'}, 404)
        slot_id = url.path.split('/')[3]
        payload = self.body()
        mode = payload.get('mode', 'empty')
        operation = payload.get('operation', 'Diversos')
        vehicles = vehicle_map()

        vehicle_id = payload.get('vehicleId') or None
        trailer_id = payload.get('trailerId') or None
        custom_plate = (payload.get('customPlate') or '').strip().upper() or None
        custom_trailer = (payload.get('customTrailer') or '').strip().upper() or None
        driver = (payload.get('driver') or '').strip() or None
        notes = (payload.get('notes') or '').strip() or None
        vehicle_kind = (payload.get('vehicleKind') or '').strip() or None
        entered_at = payload.get('enteredAt') or now()

        if mode == 'isolated' and not vehicle_id and not custom_plate:
            return self.send_json({'error': 'Informe a placa ou selecione um veículo da lista'}, 400)
        if mode == 'conjunto' and (not (vehicle_id or custom_plate) or not (trailer_id or custom_trailer)):
            return self.send_json({'error': 'Informe o cavalo e a carreta'}, 400)

        conn = db(APP_DB)
        requested_ids = {str(value) for value in (vehicle_id, trailer_id) if value}
        requested_plates = {normalize_plate(value) for value in (custom_plate, custom_trailer) if value}
        for ref_id in requested_ids:
            plate = vehicles.get(ref_id, {}).get('plate')
            if plate: requested_plates.add(normalize_plate(plate))

        active_rows = conn.execute('''
            SELECT h.*, s.code AS slot_code
            FROM slot_history h
            JOIN slots s ON s.id = h.slot_id
            WHERE h.exited_at IS NULL AND h.slot_id <> ?
        ''', (slot_id,)).fetchall()
        for existing in active_rows:
            existing_ids = {str(value) for value in (existing['vehicle_id'], existing['trailer_id']) if value}
            existing_plates = {normalize_plate(value) for value in (existing['custom_plate'], existing['custom_trailer']) if value}
            for ref_id in existing_ids:
                plate = vehicles.get(ref_id, {}).get('plate')
                if plate: existing_plates.add(normalize_plate(plate))
            if requested_ids.intersection(existing_ids) or requested_plates.intersection(existing_plates):
                duplicate_plate = next(iter(requested_plates.intersection(existing_plates)), '')
                conn.close()
                return self.send_json({
                    'error': f'Esta placa já está ocupando a vaga {existing["slot_code"]}. Libere a vaga anterior antes de alocar novamente.',
                    'code': 'DUPLICATE_ACTIVE_VEHICLE',
                    'slot': existing['slot_code'],
                    'plate': duplicate_plate
                }, 409)

        active = conn.execute('SELECT * FROM slot_history WHERE slot_id=? AND exited_at IS NULL', (slot_id,)).fetchone()
        timestamp = now()
        if active:
            conn.execute('UPDATE slot_history SET exited_at=? WHERE id=?', (timestamp, active['id']))
        if mode != 'empty':
            conn.execute('''
                INSERT INTO slot_history(slot_id, mode, operation, vehicle_id, trailer_id, custom_plate, custom_trailer, driver, notes, vehicle_kind, entered_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (slot_id, mode, operation, vehicle_id, trailer_id, custom_plate, custom_trailer, driver, notes, vehicle_kind, entered_at, timestamp))
        conn.commit()
        conn.close()
        return self.send_json({'success': True})

    def do_POST(self):
        url = urlparse(self.path)
        if url.path.startswith('/api/slots/') and url.path.endswith('/position'):
            slot_id = url.path.split('/')[3]
            payload = self.body()
            x = float(payload.get('x', 0))
            y = float(payload.get('y', 0))
            conn = db(APP_DB)
            conn.execute('UPDATE slots SET x=?, y=? WHERE id=?', (x, y, slot_id))
            conn.commit()
            conn.close()
            return self.send_json({'success': True, 'x': x, 'y': y})
        return self.send_json({'error': 'Não encontrado'}, 404)

    def static(self, name):
        path = (PUBLIC / name).resolve()
        if not str(path).startswith(str(PUBLIC.resolve())) or not path.exists() or not path.is_file():
            return self.send_json({'error': 'Arquivo não encontrado'}, 404)
        data = path.read_bytes()
        ext = path.suffix.lower()
        mime_map = {
            '.html': 'text/html; charset=utf-8',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.webp': 'image/webp',
            '.svg': 'image/svg+xml',
            '.css': 'text/css; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.json': 'application/json; charset=utf-8',
            '.webmanifest': 'application/manifest+json; charset=utf-8'
        }
        mime = 'application/manifest+json; charset=utf-8' if path.name in ('manifest.json', 'manifest.webmanifest') else mime_map.get(ext, 'application/octet-stream')
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        if path.name == 'sw.js':
            self.send_header('Service-Worker-Allowed', '/')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_): pass

if __name__ == '__main__':
    PUBLIC.mkdir(parents=True, exist_ok=True)
    init_db()
    print(f'Sistema Vagas Pátio Jaraguá: http://localhost:{PORT} (e na rede local: http://0.0.0.0:{PORT})')
    print(f'Banco de vagas: {APP_DB}')
    try:
        ThreadingHTTPServer.allow_reuse_address = True
        server = ThreadingHTTPServer((HOST, PORT), Handler)
        server.serve_forever()
    except Exception as e:
        print(f'Erro no servidor: {e}', flush=True)
