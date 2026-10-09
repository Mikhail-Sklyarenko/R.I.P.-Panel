"""Exercise the actual file entrypoint used by the panel, without PYTHONPATH help."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.parametrize('cwd_kind',['bot','unrelated'])
def test_panel_preflight_finds_real_nav_assets_from_direct_script(tmp_path,cwd_kind):
    root=Path(__file__).resolve().parents[1]
    bot=root/'vendor/csgobot'
    env=os.environ.copy()
    env.pop('PYTHONPATH',None)
    env.pop('CSGOBOT_NAV_CALIBRATION',None)
    env.update(CSGOBOT_NAV='1',CSGOBOT_NAV_PACK='auto',PYTHONDONTWRITEBYTECODE='1')
    result=subprocess.run([sys.executable,'-I','-B',str(bot/'tools/preflight.py')],
        cwd=bot if cwd_kind=='bot' else tmp_path,env=env,capture_output=True,text=True,timeout=60)
    payload=json.loads(result.stdout)
    assert not any('nav preflight failed' in e for e in payload['errors']),payload
    assert payload['nav']['ok'],payload['nav']
    assert 'cache_visual' in payload['nav']['packs_ok']
    # Missing platform/CUDA dependencies must remain fatal; fixing imports
    # must not turn the complete preflight into unconditional success.
    assert payload['ok']==(not payload['errors'])
    assert result.returncode==(0 if payload['ok'] else 1)
