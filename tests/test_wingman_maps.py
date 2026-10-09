import json
import pytest
from modules.wingman.maps import map_ready,profile_folder
from modules.wingman.telemetry import GameState
from tests.test_wingman_live import payload


def test_existing_inferno_remains_ready():
    assert map_ready('de_inferno') and profile_folder('de_inferno').name=='inferno'


@pytest.mark.parametrize('name',['de_dust2','../inferno','',None])
def test_unverified_maps_do_not_authorize_gameplay(name):
    assert not map_ready(name)
    s=GameState();assert s.accept(payload(map={'name':name}))
    assert not s.snapshot().observation.connected


def test_unknown_profile_never_falls_back_to_inferno():
    with pytest.raises(ValueError):profile_folder('../inferno')


def test_nuke_calibration_excludes_shared_floor_matches():
    folder=profile_folder('de_nuke')
    report=json.loads((folder/'calibration-report.json').read_text())
    ambiguous=set(report['ambiguous_times'])
    assert ambiguous
    for layer in ('upper','lower'):
        atlas=json.loads((folder/layer/'atlas.json').read_text())
        assert atlas['references'] and all(ref['source_time'] not in ambiguous for ref in atlas['references'])
        assert all((folder/layer/ref['image']).is_file() for ref in atlas['references'])
    assert json.loads((folder/'navigation.json').read_text())['runtime_ready']
    assert map_ready('de_nuke')


def test_missing_nuke_assets_never_authorize_gameplay(monkeypatch,tmp_path):
    import modules.wingman.maps as maps
    folder=tmp_path/'resources/wingman/nuke';folder.mkdir(parents=True)
    (folder/'navigation.json').write_text(json.dumps({'map_id':'de_nuke','runtime_ready':True,'required_assets':['missing.png']}))
    for name in ('walkable.png','objectives.json','ingress.json'):(folder/name).touch()
    monkeypatch.setattr(maps,'ROOT',tmp_path)
    assert not maps.map_ready('de_nuke')
