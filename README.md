# Vault Launcher

One-click install, update and removal of my Borderlands mods, for every Borderlands game:
Borderlands GOTY Enhanced, Borderlands 2, The Pre-Sequel, Borderlands 3, Tiny Tina's Wonderlands and Borderlands 4.

## Download

Get the newest **VaultLauncher-x.x.x.zip** from [Releases](https://github.com/mkd561234/vault-launcher/releases/latest),
right-click it and choose **Extract All**, then open **Vault Launcher.exe**.

If Windows says "Windows protected your PC", click **More info** and then **Run anyway**. The program isn't code-signed.

After that, the launcher updates itself from this page. Your downloaded mods update along with it.

## Mods

**Krieg the Psycho** for The Pre-Sequel: Borderlands 2's Psycho as a seventh Vault Hunter, with his skill trees,
Buzz Axe Rampage, heads and skins, class mods, Oz kit slams and vehicle seats.

You need:
- Borderlands 2 with its Psycho Pack (Krieg) DLC.
- The Pre-Sequel with at least one of its DLCs.

No game files are included. Krieg is rebuilt from your own copy of Borderlands 2.

## Repository layout

- `Vault Launcher.exe`: starts the launcher. Its source is in `app/exe_src`.
- `app/vault`: the launcher, written in Python. On first run it downloads its own copy of Python from python.org.
- `app/catalog`: one folder per mod. See `app/catalog/README.txt`.
- `README.txt`: the guide that ships inside the zip.
- `latest.json` and `dist/`: the newest version. Every installed launcher checks `latest.json` and downloads the zip it names, and a release is published automatically each time it changes.
