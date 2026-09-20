# Obsidian

Host-level install and uninstall scripts for the [Obsidian](https://obsidian.md) desktop app.
Same pattern as `apps/opencode`: run the script for your OS, re-run it safely any time.

## What the scripts do

| Script          | OS             | Primary method                         | Fallback                              |
| --------------- | -------------- | -------------------------------------- | ------------------------------------- |
| `install.sh`    | Linux          | Flatpak from Flathub (`--user` scope)  | Official `.deb` via `apt` (`--deb`)   |
| `uninstall.sh`  | Linux          | Removes the Flatpak                    | Removes the `.deb` package            |
| `install.ps1`   | Windows        | `winget install --id Obsidian.Obsidian`| `choco install obsidian -y`           |
| `uninstall.ps1` | Windows        | `winget uninstall`                     | `choco uninstall`                     |

Flatpak is the default on Linux because it is distro-agnostic and sandboxed. The Flathub
remote is added with `--if-not-exists`, so nothing is duplicated on repeat runs. 

**The fallback can engage on its own.** If `flatpak` is not installed, `install.sh` uses the
`.deb` path automatically, exactly as if `--deb` had been passed — that install is
machine-wide and needs `sudo`. `install.ps1` does the same with Chocolatey when `winget` is
missing, and Chocolatey is likewise machine-wide and needs an elevated prompt. Each script
says so on screen before it switches.

Every script is idempotent: it detects an existing installation first and exits without
changing anything. Detection covers the package managers above plus a plain binary already on
`PATH` (Linux) or a per-user install under `%LOCALAPPDATA%` (Windows) — in those cases the
uninstallers say what they found and which tool owns it, rather than reporting "not installed".

Each run writes `install.log` / `uninstall.log` next to the script (both are gitignored via
`*.log`). If that file is not writable, the script logs to a temp file and carries on rather
than failing.

## Usage

### Linux

```bash
cd apps/obsidian

./install.sh            # Flatpak from Flathub (default)
./install.sh --deb      # Official .deb via apt (Debian/Ubuntu, amd64 only)
./install.sh --help

./uninstall.sh          # Removes whichever of the two is present
```

**Do not run these with `sudo`.** The Flatpak is installed in `--user` scope, and a user
installation belongs to the account that owns it — running the whole script as root would
install into root's installation (invisible in your launcher), and the uninstaller would
report "not installed" while the app is still there. Both scripts detect `sudo`, print a
note and re-run themselves as the invoking user; the `.deb` path elevates on its own for
the `apt` call only.

The `--deb` path needs `curl`, `apt-get` and `sudo`. Obsidian only publishes an **amd64**
`.deb`, so on other architectures use the Flatpak.

These are Linux scripts: they depend on `flatpak` or `apt`, so macOS is not covered — use
the official `.dmg` from [obsidian.md](https://obsidian.md/download) there.

### Windows PowerShell

```powershell
cd apps\obsidian

.\install.ps1           # winget (default)
.\install.ps1 -Choco    # Chocolatey instead

.\uninstall.ps1         # Removes whichever of the two is present
```

winget installs Obsidian per-user, so run that path as your normal account rather than from
an elevated prompt, for the same reason as the Flatpak above. Chocolatey installs
machine-wide and does need an elevated prompt. If the scripts are blocked by execution
policy:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

## IMPORTANT: these scripts install the application only

They install **only the Obsidian application binary**. They do **no configuration**, and that
is deliberate.

Obsidian's configuration is **per-vault**, not per-machine. Enabled plugins, hotkeys, the
templates folder, appearance and themes all live inside each vault, in its own `.obsidian/`
folder:

```
my-vault/
├── .obsidian/          <-- the configuration lives here, with the vault
│   ├── app.json
│   ├── appearance.json
│   ├── hotkeys.json
│   ├── community-plugins.json
│   └── plugins/
└── ... your notes ...
```

That means your setup travels with the vault (through git, Syncthing, Obsidian Sync or
whatever you use), not with the installer. Nothing about it belongs in this repo, so there is
nothing here to configure.

For the same reason, `uninstall.sh` / `uninstall.ps1` remove the application and leave your
vaults — and every `.obsidian/` folder in them — completely untouched. They print the exact
command to delete the app-level data directory if you really want a clean slate.
