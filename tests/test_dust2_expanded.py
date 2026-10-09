import importlib
import importlib.util
from pathlib import Path
import numpy as np


def test_expanded_profile_preserves_walls_and_marks_uncertainty(csgobot_module_path,tmp_path):
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('build_expanded',root/'scripts/build_dust2_expanded.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    report=module.build(tmp_path)
    ground=importlib.import_module('nav.walkable').WalkableMap.load('de_dust2',tmp_path)
    assert report['experimental'] and not report['full_map_ready'] and not report['live_validated']
    assert report['usable_pixels']>250000
    assert not ground.free[140:280,610:686].any()
    assert not ground.contains((.52,.74)) # Solid central structure.
    assert not ground.contains((.01,.01))
    for point in ((.15,.65),(.45,.5),(.88,.4),(.4,.9)):
        assert ground.contains(point)
    assert not ground.visible((.4,.74),(.65,.74))
    assert np.array_equal(ground.free,importlib.import_module('nav.walkable').WalkableMap.load('de_dust2',tmp_path).free)
