"""Product Wingman session: gameplay worker admitted by the fleet agent.

Lobby, search and recovery stay in core/wingman_fleet. This module only starts
csgobot after the coordinator issued START_GAMEPLAY and a live lease exists.
The manual «current match» button remains TestSession.
"""
from __future__ import annotations

from modules.fleet_agent.live import WindowsBackend
