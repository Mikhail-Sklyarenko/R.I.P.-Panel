#!/usr/bin/env python3
"""Local Navigation Studio. Loopback only, session-token protected, no cloud."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse
import uuid
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'vendor/csgobot'))

import cv2
import numpy as np
from nav import studio
from nav.paths import resolve_nav_root, resolve_map_radar_path


class Studio:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.jobs = {}
        self.lock = threading.RLock()

    def start_job(self, data):
        with self.lock:
            if any(job['process'].poll() is None for job in self.jobs.values()):
                raise ValueError('Сначала остановите текущий сеанс')
            kind = data['kind']
            if kind not in ('record', 'drive', 'replay'):
                raise ValueError('Unknown job')
            if kind != 'replay' and sys.platform != 'win32':
                raise ValueError('Запись и управление CS2 доступны на Windows. Редактор и проверки работают здесь.')
            map_id = studio.identifier(data.get('map_id', 'de_dust2'))
            seconds = int(data.get('seconds', 120))
            if not 1 <= seconds <= 600:
                raise ValueError('Продолжительность: 1–600 секунд')
            job_id = 'session_'+uuid.uuid4().hex[:12]
            folder = studio.studio_root()/'sessions'/job_id
            folder.mkdir(parents=True)
            stop_file = folder/'stop'
            if kind == 'record':
                command = [sys.executable, '-u', str(ROOT/'scripts/nav_record.py'), '--map-id', map_id,
                           '--output', str(folder), '--seconds', str(seconds), '--stop-file', str(stop_file)]
            elif kind == 'drive':
                bundle = studio.studio_root()/'releases'/studio.identifier(data['bundle_id'])
                pack, _ = studio.load_bundle(bundle)
                map_id = pack.map_id
                command = [sys.executable, '-u', str(ROOT/'scripts/nav_live.py'), '--drive', '--bundle', str(bundle),
                           '--output', str(folder/'live.jsonl'), '--seconds', str(seconds), '--stop-file', str(stop_file)]
            else:
                video = Path(data.get('video', ''))
                if not video.is_file() or video.suffix.lower() not in ('.mp4', '.avi', '.mkv', '.mov'):
                    raise ValueError('Укажите существующий видеофайл на этом компьютере')
                if map_id != 'de_dust2':
                    raise ValueError('Прогон видео пока поддерживает Dust2')
                command = [sys.executable, '-u', str(ROOT/'scripts/nav_replay_check.py'), '--video', str(video),
                           '--output', str(folder/'replay.json'), '--seconds', str(seconds)]
            if kind == "drive" and data.get("roam") is True:
                command.append("--roam")
            with (folder/'console.log').open('w', encoding='utf-8') as output:
                process = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
            self.jobs[job_id] = {'id': job_id, 'kind': kind, 'map_id': map_id, 'folder': folder,
                                 'process': process, 'started': time.time()}
            return {'id': job_id}

    def stop_job(self, job_id):
        with self.lock:
            job = self.jobs[studio.identifier(job_id)]
            (job['folder']/'stop').touch()
            if job['kind'] == 'replay' and job['process'].poll() is None:
                job['process'].terminate()  # Read-only child; never kill an input process.
            return {'stopping': True}

    def status(self):
        results = []
        with self.lock:
            for job in self.jobs.values():
                folder = job['folder']
                log = folder/'console.log'
                tail = log.read_bytes()[-5000:].decode('utf-8', errors='replace') if log.exists() else ''
                pose = None
                for name in ('live.jsonl', 'trace.jsonl'):
                    path = folder/name
                    if path.exists():
                        with path.open('rb') as stream:
                            stream.seek(max(0, path.stat().st_size-12000))
                            lines = stream.read().splitlines()
                        for line in reversed(lines):
                            try:
                                row = json.loads(line)
                                if 'valid' in row:
                                    pose = row
                                    break
                            except (ValueError, UnicodeError):
                                continue
                summary = None
                for name in ('live.summary.json', 'summary.json'):
                    path = folder/name
                    if path.exists():
                        try:
                            summary = json.loads(path.read_text(encoding='utf-8'))
                        except ValueError:
                            pass
                results.append({'id': job['id'], 'kind': job['kind'], 'map_id': job['map_id'],
                    'exit_code': job['process'].poll(), 'elapsed': round(time.time()-job['started']),
                    'log': tail, 'pose': pose, 'summary': summary, 'folder': str(folder)})
        return results

    def trace_from_job(self, job_id):
        job = self.jobs[studio.identifier(job_id)]
        if job['process'].poll() is None:
            raise ValueError('Сначала завершите сеанс')
        for name in ('trace.jsonl', 'live.jsonl', 'replay.json'):
            path = job['folder']/name
            if path.exists():
                return studio.import_trace(path.read_text(encoding='utf-8'), job['map_id'])
        raise ValueError('Нет записанных позиций')

    def close(self):
        for job_id in list(self.jobs):
            self.stop_job(job_id)
        for job in self.jobs.values():
            try:
                job['process'].wait(timeout=2)
            except subprocess.TimeoutExpired:
                if job['kind'] != 'drive':
                    job['process'].terminate()


def handler_type(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, value, content_type='application/json', status=200):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self, query, root=False):
            token = query.get('token', [''])[0] if root else self.headers.get('X-Nav-Token', '')
            origin = self.headers.get('Origin')
            origins = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
            return secrets.compare_digest(token, app.token) and (not origin or origin in origins)

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if not self.authorized(query, root=url.path == '/'):
                self.send({'error': 'Unauthorized'}, status=403)
                return
            try:
                map_id = studio.identifier(query.get('map', ['de_dust2'])[0])
                if url.path == '/':
                    page = (ROOT/'resources/nav/studio.html').read_text(encoding='utf-8').replace('__SESSION_TOKEN__', app.token)
                    self.send(page.encode('utf-8'), 'text/html; charset=utf-8')
                elif url.path == '/api/state':
                    project = studio.load_project(map_id)
                    maps = [p.parent.name for p in (resolve_nav_root()/'maps').glob('*/radar.png')]
                    self.send({'project': project, 'maps': sorted(maps), 'report': studio.check_project(project),
                               'platform': sys.platform, 'storage': str(studio.studio_root())})
                elif url.path == '/api/map':
                    self.send(resolve_map_radar_path(map_id).read_bytes(), 'image/png')
                elif url.path == '/api/mask':
                    mask = studio.build_mask(studio.load_project(map_id))
                    rgba = np.zeros((*mask.shape, 4), np.uint8)
                    rgba[mask > 0] = (145, 220, 35, 85)
                    self.send(cv2.imencode('.png', rgba)[1].tobytes(), 'image/png')
                elif url.path == '/api/jobs':
                    self.send(app.status())
                else:
                    self.send({'error': 'Not found'}, status=404)
            except Exception as exc:
                self.send({'error': str(exc)}, status=400)

        def do_POST(self):
            if not self.authorized({}):
                self.send({'error': 'Unauthorized'}, status=403)
                return
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 12_000_000:
                    raise ValueError('Request size limit is 12 MB')
                data = json.loads(self.rfile.read(length))
                with app.lock:
                    if self.path == '/api/save':
                        studio.save_project(data['project'])
                        result = {'saved': True}
                    elif self.path == '/api/check':
                        result = studio.check_project(data['project'])
                    elif self.path == '/api/export':
                        result = studio.export_bundle(data['project'], data['route_id'])
                    elif self.path == '/api/import':
                        result = studio.import_trace(data['text'], studio.identifier(data['map_id']))
                    elif self.path == '/api/import-job':
                        result = app.trace_from_job(data['id'])
                    elif self.path == '/api/job':
                        result = app.start_job(data)
                    elif self.path == '/api/stop':
                        result = app.stop_job(data['id'])
                    elif self.path == '/api/shutdown':
                        app.close()
                        threading.Thread(target=self.server.shutdown, daemon=True).start()
                        result = {'closed': True}
                    else:
                        raise ValueError('Unknown action')
                self.send(result)
            except Exception as exc:
                self.send({'error': str(exc)}, status=400)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    app = Studio()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_type(app))
    server.daemon_threads = True
    url = f'http://127.0.0.1:{server.server_port}/?token={app.token}'
    print(url, flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()


if __name__ == '__main__':
    main()
