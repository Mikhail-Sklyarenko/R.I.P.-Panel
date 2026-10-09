"""Map discovery must not block combat or publish results from old sessions."""
import importlib
import threading
import time
import numpy as np


def test_async_discovery_does_not_block_and_reset_discards_inflight(csgobot_module_path):
    mod = importlib.import_module('nav.map_selector')
    entered, release = threading.Event(), threading.Event()
    class Scanner:
        def __init__(self, _): self.last_scores = {}
        def update(self, frame, *, now):
            entered.set();release.wait(2)
            self.pending, self.count = 'de_inferno', 3
            return 'de_inferno'
    selector = mod.AsyncVisualMapSelector(None, selector_factory=Scanner)
    frame = np.zeros((10,10,3),np.uint8)
    try:
        assert selector.update(frame,now=1.) is None
        assert entered.wait(1)
        before = time.perf_counter()
        assert selector.update(frame,now=1.1) is None
        assert time.perf_counter()-before < .1
        selector.reset();release.set()
        selector.close()
        assert selector._result is None
        assert not selector._thread.is_alive()
    finally:
        release.set();selector.close()


def test_map_result_expires_and_is_consumed_once(csgobot_module_path):
    mod = importlib.import_module('nav.map_selector')
    class Scanner:
        def __init__(self,_): pass
        def update(self,*args,**kwargs): return None
    selector = mod.AsyncVisualMapSelector(None,selector_factory=Scanner)
    frame = np.zeros((2,2,3),np.uint8)
    try:
        selector.next_at=100.
        selector._result=(selector._generation,1.,'de_inferno')
        assert selector.update(frame,now=10.) is None
        selector._result=(selector._generation,10.,'de_inferno')
        assert selector.update(frame,now=10.1)=='de_inferno'
        assert selector.update(frame,now=10.2) is None
    finally:selector.close()
