WEAPON REPOSITION 76 - VIEWMODEL EDITOR 1.0.0
=============================================

A Windows app for setting where every gun sits on screen, with a live 3D preview built from your own
game files, plus the viewmodel / FOV / camera settings that Quick Configuration offers. It builds the
Weapon Reposition 76 archive for you with your own positions.

This is NOT a mod-manager download. Do not install this zip with a mod manager or put it in Data.
(If you only want the default gun positions, download the mod-manager version instead.)


INSTALL
-------
1. Extract the "FO76 Viewmodel Editor" folder anywhere (Desktop, Documents, ...).
2. Run "FO76 Viewmodel Editor.exe".
   It finds Fallout 76 in your Steam libraries or a Microsoft Store / Game Pass install. If it can't,
   it asks for the folder that contains Fallout76.exe (Steam) or Project76_GamePass.exe (Game Pass).
   The first start takes ~10-20 seconds while it indexes the game's archives (later starts are fast).

Nothing is installed system-wide. Settings, a cache of extracted game files (~100 MB) and backups go
to %APPDATA%\FO76 Viewmodel Editor. To uninstall, delete the folder and that AppData folder.


GUN POSITIONS
-------------
- Pick a weapon on the left. X = right, Y = forward, Z = up (game units). Drag the sliders, type a
  value, or use the arrow keys / Page Up / Page Down (hold Shift for bigger steps).
- "Gun Mover default" = the mod's position, "Vanilla" = unmoved, "Undo changes" = what's installed.
- Hip / Aiming / Pip-Boy switch the preview. Aiming is never changed by the mod, so sights stay
  lined up. "Vanilla outline" draws a faint outline of the unmoved gun.
- Drag in the preview to look around the gun, scroll to zoom, double-click to return to the game view.
- The part menus only change what the preview shows; every mod of a weapon uses the same animations.

Click "Install gun positions" (with the game closed) to bake your positions into
Data\WeaponReposition76.ba2. It takes about a minute. The archive it replaces is backed up once to
%APPDATA%\FO76 Viewmodel Editor\backups. If the archive isn't in the [Archive] sResourceArchive2List of
Fallout76Custom.ini (Project76Custom.ini on Game Pass) yet, the app adds it (if a mod manager manages that
list, add it there too).
If you already installed the mod-manager version, the app rebuilds that same archive.


FOV & CAMERA
------------
Viewmodel FOV (hands, gun and Pip-Boy - use the Pip-Boy preview), world FOV, the [Camera] FOVs,
3rd-person aim FOV and the over-the-shoulder camera position. Changes show in the preview right away
and are written to Documents\My Games\Fallout 76\Fallout76Custom.ini (Project76Custom.ini for the Game Pass
version) when you click Save; the file from before the first change is kept as *.pre-vmeditor.bak.
Restart the game for FOV changes to apply. FOV sliders use the game's own 70-120 range.

There is no separate Pip-Boy FOV in Fallout 76: the Pip-Boy uses the viewmodel FOV.


NOTES
-----
- The preview uses the game's own meshes and animations and matches in-game screenshots at 16:9.
  Other screen shapes are assumed to keep the vertical view (Hor+).
- Windows may warn about an unknown app the first time (the exe isn't code-signed).
- Built with Electron, three.js and Python 3.13 (bundled; their licenses are in the app folder).


CREDITS
-------
- Gun Mover by jarari (Fallout 4) - the original mod; ported with the author's permission.
- First Person FOV Overhaul by HumanKvas (Fallout 4) - the per-weapon offsets.
- Quick Configuration (Fallout 76 Quick Configuration) for the idea of the FOV page.
- Bethesda Game Studios - the original animations and meshes (read from your install, not included).
