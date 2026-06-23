Farm Panel Prototype — portable distribution
============================================

1) Prerequisites on this PC:
   - Windows 10/11
   - Steam + CS2 installed
   - Node.js LTS (for looter)

2) One-time in this folder:
   cd vendor\looter
   npm install

3) First run:
   - Start FarmPanel.exe
   - Config #1: steam_path, cs2_path, trade_offer_link
   - Set test_mode: false in data\config.yaml (created on first save)
   - Import accounts: vault_cli.bat add --login USER --password PASS --mafile path\to.maFile

4) Farm:
   - Check accounts in UI
   - Start Selected (one account for first test)
   - Watch Main log: steam_ok → in_dm → level_up → drop → loot_ok → DONE

5) If hung:
   - Kill ALL CS & Steam (Utils)
   - See docs\WINDOWS_FIRST_RUN.md in source repo (or copy to this folder)

Full guide: farm-panel-prototype/docs/WINDOWS_FIRST_RUN.md
