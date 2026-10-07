Vault Launcher mod catalog
==========================
Each folder here is one mod. mod.json fields:
  id        unique id (folder name)
  name      shown in the launcher
  game      bl1e | bl2 | tps | bl3 | wl | bl4
  version   bump it to push an update to everyone who has the mod installed
  kind      "sdkmod"  -> copies payload/ into the game's sdk_mods folder (installs the SDK first)
            "krieg"   -> Krieg's rebuild-from-Borderlands-2 recipe
  summary / details / icon (an .svg in this folder)
  nexus     optional {game_domain, mod_id} for an "Open on Nexus" link

To add a mod: make a folder here with mod.json, payload/ and icon.svg, bump "version" in
app/release.json, zip the VaultLauncher folder and upload it to the launcher's Nexus page as the
new main file. Everyone signed in gets the new launcher, and the new mod shows up under its game.
