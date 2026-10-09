"""Canonical product mode shared by source and newly built panel entrypoints."""
import os


def configure_farm_runtime():
    # Farm sessions always use measured navigation; historical UI values must
    # not silently reactivate the macro patrol or select an obsolete route.
    os.environ.update({
        "CSGOBOT_NAV": "1",
        "CSGOBOT_NAV_MODE": "expanded_roam",
        "CSGOBOT_NAV_PACK": "auto",
        "CSGOBOT_AUTO_ACTIVATE": "1",
    })
    os.environ.setdefault("CSGOBOT_NAV_READ_ONLY", "0")
