"""A readiness pixel probe alone is never evidence of a map transition."""


def named_match_ready(detected, source):
    return source == "match_ready" and detected in ("dust2", "mirage", "inferno", "vertigo", "cache")


def active_map_confirmed(map_id, state):
    return (state.locked and state.pending_count == 0
            and state.confirmed_script in ("dust2", "mirage", "inferno", "vertigo", "cache")
            and map_id == "de_" + state.confirmed_script)
