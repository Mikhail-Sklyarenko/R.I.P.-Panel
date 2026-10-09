import importlib
import importlib.util
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest


@pytest.fixture
def service(csgobot_module_path, tmp_path, monkeypatch):
    monkeypatch.setenv('FARM_PANEL_DATA_DIR', str(tmp_path))
    return importlib.import_module('nav.studio')


def test_initial_project_exports_a_runnable_immutable_bundle(service):
    p = service.new_project()
    assert service.check_project(p)['ready_routes'] == 1
    release = service.export_bundle(p, 'mid')
    pack, ground = service.load_bundle(release['path'])
    assert pack.pack_id == 'studio_mid' and len(pack.goals) == 2
    assert ground.plan((.458, .432), (.461, .606))
    second = service.export_bundle(p, 'mid')
    assert second['id'] != release['id']
    assert not list((service.studio_root()/'releases').glob('.building-*'))
    with (Path(release['path'])/'pack.yaml').open('a') as f:
        f.write('\n# changed')
    with pytest.raises(ValueError, match='Release changed'):
        service.load_bundle(release['path'])


def test_draft_walkable_never_expands_runtime_mask(service):
    p = service.new_project()
    region = {'id':'new_area','kind':'walkable','status':'draft','evidence':'',
              'points':[[.7,.7],[.9,.7],[.9,.9],[.7,.9]]}
    p['regions'] = [region]
    assert service.build_mask(p)[820,820] == 0
    region['status'] = 'verified'
    with pytest.raises(ValueError, match='verification note'):
        service.build_mask(p)
    region['evidence'] = 'Manual traversal reviewed in test fixture'
    assert service.build_mask(p)[820,820] == 255


def test_obstacles_win_and_disconnected_route_cannot_export(service):
    p = service.new_project()
    cut = {'id':'wall','kind':'blocked','status':'draft','evidence':'',
           'points':[[.4,.5],[.55,.5],[.55,.52],[.4,.52]]}
    p['regions'] = [cut]
    assert not service.check_project(p)['routes'][0]['ready']
    with pytest.raises(ValueError, match='не прошёл'):
        service.export_bundle(p,'mid')


@pytest.mark.parametrize('fault',['map_hash','nan','path','polygon'])
def test_invalid_projects_cannot_be_saved(service, fault):
    p = service.new_project()
    if fault == 'map_hash': p['map_sha256'] = 'wrong'
    if fault == 'nan': p['routes'][0]['points'][0][0] = float('nan')
    if fault == 'path': p['map_id'] = '../escape'
    if fault == 'polygon':
        p['regions'] = [{'id':'x','kind':'walkable','status':'draft','points':[[.1,.1],[.3,.3],[.1,.3],[.3,.1]]}]
    with pytest.raises(ValueError): service.save_project(p)


def test_import_preserves_gaps_and_never_bridges_teleports(service):
    rows = [{'t':t,'x':x,'y':.45,'valid':valid,'confidence':.8} for t,x,valid in
            [(0,.45,True),(.1,.46,True),(.2,.47,False),(.3,.47,True),(.4,.48,True),(.5,.8,True),(.6,.81,True)]]
    trace = service.import_trace('\n'.join(json.dumps(r) for r in rows), 'de_dust2')
    assert len(trace['segments']) == 3 and trace['rejected'] == 1
    assert trace['status'] == 'draft'
    assert all(abs(s[-1][0]-s[0][0]) < .02 for s in trace['segments'])
    assert service.new_project()['regions'] == []


def test_trace_from_wrong_map_is_rejected(service):
    with pytest.raises(ValueError, match='another map'):
        service.import_trace(json.dumps({'map_id':'de_mirage','frames':[]}), 'de_dust2')


def test_save_reload_roundtrip(service):
    p = service.new_project()
    p['routes'].append({'id':'short','name':'Short test','points':[[.458,.45],[.46,.55]]})
    service.save_project(p)
    assert service.load_project() == p
    assert service.check_project(p)['ready_routes'] == 2


def server_module():
    path = Path(__file__).resolve().parents[1]/'scripts/nav_studio.py'
    spec = importlib.util.spec_from_file_location('studio_server_test',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_http_api_requires_token_and_checks_exports(service):
    module = server_module()
    app = module.Studio()
    server = ThreadingHTTPServer(('127.0.0.1',0),module.handler_type(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    def request(path, data=None, token=None, origin=None):
        headers = {'X-Nav-Token':token or app.token,'Content-Type':'application/json'}
        if origin: headers['Origin']=origin
        r=urllib.request.Request(base+path, json.dumps(data).encode() if data else None, headers=headers)
        with urllib.request.urlopen(r) as response: return json.load(response)
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            request('/api/state',token='wrong')
        assert error.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as error:
            request('/api/save',{'project':service.new_project()},origin='https://untrusted.example')
        assert error.value.code == 403
        p=request('/api/state')['project']
        assert request('/api/check',{'project':p})['ready_routes']==1
        r=request('/api/export',{'project':p,'route_id':'mid'})
        assert service.load_bundle(r['path'])[0].pack_id=='studio_mid'
    finally:
        server.shutdown();server.server_close();thread.join(2)


@pytest.mark.parametrize("roam", [False, True])
def test_stopping_drive_uses_stop_signal_not_process_kill(service, monkeypatch, roam):
    module=server_module()
    monkeypatch.setattr(module.sys,'platform','win32')
    class Child:
        def __init__(self,command,**kw): self.command=command;self.killed=False
        def poll(self): return None
        def terminate(self): self.killed=True
    monkeypatch.setattr(module.subprocess,'Popen',Child)
    release=service.export_bundle(service.new_project(),'mid')
    app=module.Studio()
    result=app.start_job({'kind':'drive','map_id':'de_dust2','bundle_id':release['id'], 'roam':roam})
    job=app.jobs[result['id']]
    assert '--bundle' in job['process'].command and '--stop-file' in job['process'].command
    assert ('--roam' in job['process'].command) == roam
    app.stop_job(result['id'])
    assert (job['folder']/'stop').exists() and not job['process'].killed
