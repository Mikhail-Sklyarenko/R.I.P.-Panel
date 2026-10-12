# Phase 02 software report

Source SHA: `5418eaca345de00547e5ef662e442f5824a4fb28`  
Branch: `fix/fleet-phase02-catalog-ui-lan-acceptance`

This patch closed the two remaining catalog defects, wired the Wingman tab to those rules, opened a real panel window, and proved HTTPS loopback. Fleet profile: `200 passed in 68.75s`. Full pytest excluding `test_csgobot*.py`: `11 failed, 1015 passed, 3 skipped`. It did not start Phase 03, did not change `main`, and did not run on four physical PCs.

## Acceptance matrix

| ID | Scenario | Environment | Expected | Actual | Evidence | Status |
|---|---|---|---|---|---|---|
| CATALOG_A1 | v4 head generation 150 vs current snapshot generation 1 | pytest fixture | Snapshot accepted; inherited head not used for PREPARE | Accepted; PREPARE blocked until replacement | `tests/test_fleet_catalog_acceptance.py` | PASSED |
| CATALOG_A2 | Previous-registration catalog still fresh | pytest | Choose/PREPARE refused | Refused with stale-catalog message | same file | PASSED |
| SIM_E2E | Four in-process agents | pytest | READY then conflict then not READY | Passed on identity-integrity tests | `tests/test_fleet_identity_integrity.py` | PASSED |
| WIN_UI | Real Farm Panel window | this Windows host, isolated data dir | Tab, buttons, start-run gate, no Steam/CS2 | Window opened; buttons clicked; gate held | `docs/fleet/phase-02/evidence/` | PASSED |
| DPI_125 | 1920×1080 @ 125% | OS scale | Readable layout | OS scale was 100% | `evidence/display.json` | NOT_TESTED |
| TLS_LOOP | HTTPS 127.0.0.1 health + operator 403 | pytest + curl.exe | Valid TLS, no `-k` | Passed | `tests/test_fleet_secure_lan.py` | PASSED |
| TWO_PC | Two hosts HTTPS heartbeat | LAN | Heartbeat | No second PC | — | BLOCKED |
| FOUR_PC | Four hosts | LAN | Four sessions | No extra PCs | `FOUR_PC_TEST_RUNBOOK.md` | BLOCKED |
| STEAM | Real signed-in identity | live Steam | VERIFIED | Steam not started | — | BLOCKED |

`four_pc_proven` remains false.
