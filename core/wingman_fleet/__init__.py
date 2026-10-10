"""Distributed Wingman Inferno product: coordinator, pair/run FSM, durable store.

The coordinator never issues OS input; it only decides which bounded command a
specific agent may execute next. In-match logic stays in modules/wingman.
"""

PROTOCOL_VERSION = 3
MVP_MAP = "de_inferno"
MVP_MODE = "scrimcomp2v2"
