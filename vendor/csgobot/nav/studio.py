"""Navigation authoring, evidence import and immutable runnable releases."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import uuid

import cv2
import numpy as np
import yaml

from nav.paths import _data_dir, resolve_map_radar_path, resolve_visual_profile_file
from nav.pack import load_nav_pack, parse_nav_pack_data
from nav.walkable import WalkableMap, read_grayscale


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', value):
        raise ValueError('Invalid identifier')
    return value


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def studio_root():
    return _data_dir()/'nav_studio'


def point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('Point must be [x, y]')
    result = [float(v) for v in value]
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in result):
        raise ValueError('Point outside map')
    return result


def validate_project(project):
    identifier(project['map_id'])
    if project.get('version') != 1:
        raise ValueError('Unsupported project version')
    if project.get('map_sha256') != digest(resolve_map_radar_path(project['map_id'])):
        raise ValueError('Map changed: review this project against the current map')
    clearance = float(project.get('clearance_px', 6))
    if not math.isfinite(clearance) or not 1 <= clearance <= 40:
        raise ValueError('Clearance must be between 1 and 40 map pixels')
    for key, limit in [('regions', 100), ('routes', 50)]:
        items = project.get(key, [])
        if not isinstance(items, list) or len(items) > limit:
            raise ValueError(f'Too many {key}')
        ids = set()
        for item in items:
            item_id = identifier(item['id'])
            if item_id in ids:
                raise ValueError('Duplicate identifier')
            ids.add(item_id)
            points = item.get('points', [])
            if not isinstance(points, list) or len(points) > 200:
                raise ValueError('Too many points')
            for p in points:
                point(p)
            if key == 'regions':
                if len(points) < 3 or item.get('kind') not in ('walkable', 'blocked'):
                    raise ValueError('A region needs a polygon and a valid kind')
                if item.get('status') not in ('draft', 'verified'):
                    raise ValueError('Invalid region status')
                if item['status'] == 'verified' and not str(item.get('evidence', '')).strip():
                    raise ValueError('Verified regions require a verification note')
                polygon = np.asarray(points, dtype=np.float32)
                if cv2.contourArea(polygon) < .00001:
                    raise ValueError('Polygon has no usable area')
                def cross(a, b, c):
                    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
                for i in range(len(points)):
                    a, b = points[i], points[(i+1)%len(points)]
                    for j in range(i+2, len(points)):
                        if i == 0 and j == len(points)-1:
                            continue
                        c, d = points[j], points[(j+1)%len(points)]
                        if cross(a,b,c)*cross(a,b,d) < 0 and cross(c,d,a)*cross(c,d,b) < 0:
                            raise ValueError('Polygon crosses itself')
    return project


def new_project(map_id='de_dust2'):
    identifier(map_id)
    project = {'version': 1, 'map_id': map_id, 'map_sha256': digest(resolve_map_radar_path(map_id)),
               'clearance_px': 6, 'regions': [], 'routes': [], 'traces': []}
    if map_id == 'de_dust2':
        project['routes'] = [{'id': 'mid', 'name': 'Mid — исходный маршрут',
                              'points': [[.458, .432], [.461, .606]], 'evidence': 'Исходный маршрут MVP'}]
    return project


def load_project(map_id='de_dust2'):
    path = studio_root()/'projects'/f'{identifier(map_id)}.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else new_project(map_id)


def save_project(project):
    validate_project(project)
    atomic_json(studio_root()/'projects'/f"{project['map_id']}.json", project)


def build_mask(project):
    validate_project(project)
    radar = cv2.imread(str(resolve_map_radar_path(project['map_id'])))
    if radar is None:
        raise ValueError('Map image missing')
    h, w = radar.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    meta_path = resolve_visual_profile_file(project['map_id'], 'navigation.json')
    if meta_path.is_file():
        WalkableMap.load(project['map_id'])  # Validate dimensions and map fingerprint.
        mask = read_grayscale(meta_path.parent/'walkable.png')
    # Obstacles always win, independently of drawing order. Draft walkable
    # polygons remain visual proposals and never expand runtime free space.
    for kind in ('walkable', 'blocked'):
        for region in project['regions']:
            if region['kind'] != kind or (kind == 'walkable' and region['status'] != 'verified'):
                continue
            points = np.rint(np.asarray(region['points'])*[w-1, h-1]).astype(np.int32)
            cv2.fillPoly(mask, [points], 255 if kind == 'walkable' else 0)
    return mask


def check_project(project):
    mask = build_mask(project)
    ground = WalkableMap(mask, clearance_px=project['clearance_px'])
    reports = []
    for route in project['routes']:
        points = route['points']
        errors, paths = [], []
        if len(points) < 2:
            errors.append('Нужны минимум две цели')
        for index, p in enumerate(points):
            if not ground.contains(p):
                errors.append(f'Цель {index+1} вне разрешённых проходов с учётом отступа')
        if not errors:
            for index, (a, b) in enumerate(zip(points, points[1:]+points[:1])):
                path = ground.plan(a, b)
                if not path:
                    errors.append(f'Нет пути {index+1} → {(index+1)%len(points)+1}')
                paths.append(path)
        reports.append({'id': route['id'], 'ready': not errors, 'errors': errors, 'paths': paths,
                        'live_validated': False})
    return {'map_id': project['map_id'], 'routes': reports,
            'ready_routes': sum(r['ready'] for r in reports),
            'draft_regions': sum(r['status'] == 'draft' for r in project['regions']),
            'note': 'Геометрическая проверка не подтверждает прохождение в игре.'}


def import_trace(text, map_id):
    """Split at missing poses/time gaps/teleports; never connect across them."""
    if len(text) > 12_000_000:
        raise ValueError('Trace too large (12 MB maximum)')
    try:
        parsed = json.loads(text)
        rows = parsed.get('frames', []) if isinstance(parsed, dict) else parsed
        if isinstance(parsed, dict) and parsed.get('map_id', map_id) != map_id:
            raise ValueError('Trace belongs to another map')
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(rows, list) or len(rows) > 100000:
        raise ValueError('Invalid trace')
    segments, current, previous, rejected, accepted = [], [], None, 0, 0
    def split():
        nonlocal current, previous
        if len(current) >= 2:
            simplified = cv2.approxPolyDP(np.float32(current), .002, False).reshape(-1, 2).tolist()
            if len(simplified) >= 2:
                segments.append(simplified)
        current, previous = [], None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid trace row')
        if row.get('map_id', map_id) != map_id:
            raise ValueError('Trace belongs to another map')
        if row.get('type') == 'identity':
            if row.get('map_id', map_id) != map_id:
                raise ValueError('Trace belongs to another map')
            continue
        try:
            p = point([row['x'], row['y']])
            stamp = float(row.get('t', row.get('time')))
            confidence = float(row.get('confidence', .45))
            valid = row.get('valid') is True and math.isfinite(stamp) and .45 <= confidence <= 1
        except (KeyError, ValueError, TypeError):
            valid = False
        if not valid:
            rejected += 1
            split()
            continue
        if previous is not None:
            dt = stamp-previous[0]
            distance = math.dist(p, previous[1])
            if not 0 < dt <= .5 or distance > .05+.25*dt:
                split()
        accepted += 1
        if not current or math.dist(p, current[-1]) >= .002:
            current.append(p)
        previous = (stamp, p)
    split()
    if not segments:
        raise ValueError('Нет непрерывного прохода с достоверной позицией')
    return {'id': 'trace_'+uuid.uuid4().hex[:10], 'map_id': map_id, 'segments': segments[:100],
            'accepted': accepted, 'rejected': rejected, 'status': 'draft',
            'note': 'Импорт не подтверждает проходимость и не расширяет маску автоматически.'}


def export_bundle(project, route_id):
    report = check_project(project)
    checked = next((r for r in report['routes'] if r['id'] == route_id), None)
    if checked is None or not checked['ready']:
        raise ValueError('Маршрут не прошёл проверку: '+str(checked['errors'] if checked else 'not found'))
    route = next(r for r in project['routes'] if r['id'] == route_id)
    goals = [{'id': f'point_{i+1}', 'x': p[0], 'y': p[1], 'arrive_radius': .006} for i, p in enumerate(route['points'])]
    pack = {'meta': {'pack_id': 'studio_'+identifier(route_id), 'map_id': project['map_id'], 'version': '1.0.0'},
            'strategy': 'route_cycle', 'goal': goals[0], 'goals': goals,
            'routing': {'mode': 'cycle', 'dwell_at_goal_sec': 1., 'direct_goal_dist': 0.},
            'humanize': {'turn_rate_deg_per_sec': 100., 'forward_jitter_chance': 0.}, 'entries': []}
    parse_nav_pack_data(pack)
    releases = studio_root()/'releases'
    releases.mkdir(parents=True, exist_ok=True)
    bundle_id = 'route_'+uuid.uuid4().hex[:12]
    temporary = Path(tempfile.mkdtemp(prefix='.building-', dir=releases))
    try:
        (temporary/'pack.yaml').write_text(yaml.safe_dump(pack, allow_unicode=True), encoding='utf-8')
        if not cv2.imwrite(str(temporary/'walkable.png'), build_mask(project)):
            raise OSError('Cannot write mask')
        atomic_json(temporary/'navigation.json', {'map_id': project['map_id'], 'map_sha256': project['map_sha256'],
                    'clearance_px': project['clearance_px'], 'live_validated': False})
        atomic_json(temporary/'project.json', project)
        atomic_json(temporary/'report.json', checked)
        names = ['pack.yaml', 'walkable.png', 'navigation.json', 'project.json', 'report.json']
        atomic_json(temporary/'release.json', {'id': bundle_id, 'map_id': project['map_id'],
                    'files': {name: digest(temporary/name) for name in names}})
        load_bundle(temporary)
        temporary.rename(releases/bundle_id)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {'id': bundle_id, 'path': str(releases/bundle_id), 'report': checked}


def load_bundle(folder):
    folder = Path(folder)
    manifest = json.loads((folder/'release.json').read_text(encoding='utf-8'))
    expected = {'pack.yaml', 'walkable.png', 'navigation.json', 'project.json', 'report.json'}
    if set(manifest['files']) != expected:
        raise ValueError('Incomplete release')
    for name in expected:
        if digest(folder/name) != manifest['files'][name]:
            raise ValueError(f'Release changed: {name}')
    pack = load_nav_pack(folder/'pack.yaml')
    if pack.map_id != manifest['map_id']:
        raise ValueError('Release map mismatch')
    ground = WalkableMap.load(pack.map_id, folder)
    points = [(g.x, g.y) for g in pack.goals]
    if len(points) < 2 or not all(ground.plan(a, b) for a, b in zip(points, points[1:]+points[:1])):
        raise ValueError('Release route is disconnected')
    return pack, ground
