VAULT LAUNCHER  -  version 2.1.7
================================

One launcher for my Borderlands mods: download, update, repair and remove them for every game.
  Borderlands GOTY Enhanced, Borderlands 2, The Pre-Sequel, Borderlands 3, Tiny Tina's
  Wonderlands and Borderlands 4.
Games are found through Steam and the Epic Games launcher; any other folder can be chosen.
For each game it also installs the Python SDK mod manager the mods run on (from bl-sdk on GitHub).

MODS IN THIS RELEASE
  Krieg the Psycho (The Pre-Sequel)
    Borderlands 2's Psycho as a seventh Vault Hunter: his skill trees, Buzz Axe Rampage, heads and
    skins, class mods, Oz kit slams and vehicle seats.
    Needs, installed on Steam:
      * Borderlands 2 with its "Psycho Pack" (Krieg) DLC
      * The Pre-Sequel with at least one of its DLCs (any: Lady Hammerlock, Handsome Jack,
        Claptastic Voyage, Holodome, Shock Drop, Ultimate Vault Hunter pack). The Pre-Sequel only
        loads DLC characters through a DLC licence you own.
    No game files are included: Krieg is rebuilt from YOUR copy of Borderlands 2.
    Other Borderlands 2 DLCs you own add his extra heads, skins and DLC class mods.

INSTALL
  1. Extract this zip anywhere (right-click > Extract All) and double-click "Vault Launcher.exe".
     If Windows shows "Windows protected your PC", click "More info" > "Run anyway": the
     program is not code-signed, which costs money, so Windows does not recognise it yet.
     The first time it downloads a private copy of Python (about 10 MB, from python.org, checked
     against the official checksum) into %LOCALAPPDATA%\VaultLauncher. Nothing is installed
     system-wide.
  2. Pick a game on the left, then click "Download" on a mod under Uninstalled. Anything still
     missing is listed on the mod in red. Downloaded mods move to the Downloaded section; mods you
     uninstall go back to Uninstalled, where you can redownload them.
  3. Click "Play".
  The launcher adds "Vault Launcher" shortcuts to your desktop and Start menu, so you can delete
  the zip afterwards. If Windows blocks writing to a game folder, run it as administrator.

COMING FROM THE KRIEG LAUNCHER
  Vault Launcher replaces it. The first start moves your settings, Nexus sign-in and any backup
  over from %LOCALAPPDATA%\KriegTPS, swaps the shortcuts and removes the old folder. Krieg stays
  installed.

UPDATES
  Vault Launcher updates itself from https://github.com/mkd561234/vault-launcher when you
  open it (and at most once an hour while you play with Krieg). Your downloaded mods update with
  it; if their game is running, they update after you close it.
  A newer VaultLauncher-x.x.x.zip saved in your Downloads folder is installed the same way.

BACK UP YOUR SAVES
  A save that uses a mod character (like Krieg) only loads while that mod is installed.
  Pre-Sequel saves: Documents\My Games\Borderlands The Pre-Sequel\WillowGame\SaveData

UNINSTALL
  "Uninstall" on a mod removes only that mod's files and moves it to Uninstalled. The mod SDK stays for your other mods.
  To remove Vault Launcher itself: uninstall your mods, then delete %LOCALAPPDATA%\VaultLauncher
  and its two shortcuts.

TROUBLESHOOTING
  Launcher log:   %LOCALAPPDATA%\VaultLauncher\launcher.log
  Krieg's log:    <Pre-Sequel folder>\sdk_mods\KriegTPS\krieg_log.txt
  "Borderlands 2 files differ": let Steam verify Borderlands 2 (Properties > Installed Files).
