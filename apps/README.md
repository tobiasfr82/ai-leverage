# Apps

The programs in `apps/` run on this PC itself, outside Docker: Obsidian, VS Code, Claude
Code, Claude Desktop and OpenCode. `manage.sh` lists them under **APPS**, and every app gets
the same actions, whatever it's installed with:

| Action             | What it does                                                                                       |
| ------------------ | -------------------------------------------------------------------------------------------------- |
| **Install**        | Installs it from the source its `app.conf` names. Does nothing if it's already there.               |
| **Update**         | Checks online for its newest stable release, says what it would install, and asks. First it saves the version it replaces. |
| **Revert**         | Goes back to that saved version and holds it there, so a release that broke something stays away.  |
| **Hold / Release** | Hold keeps it at its version, so Update skips it. Release ends the hold.                            |
| **Uninstall**      | Removes the program and the source it came from. Your own files and settings stay.                  |

The menu shows each app's state: **[INSTALLED]**, **[HELD]** (installed, and Update skips
it), **[OTHER INSTALL]** (installed some other way, and where) or **[NOT INSTALLED]**.

- **Stable releases only.** Where a maker offers a stable and a faster channel, the app
  follows stable: Claude Code's stable apt channel, VS Code without Insiders, Obsidian's
  release on Flathub, and OpenCode's GitHub releases without pre-releases.
- **Nothing here updates on its own.** Update goes online when you choose it.
- **One revert point per app:** the version the last Update replaced, kept in
  `apps/<app>/data/revert/` (git-ignored). For an apt app that's the package file, about
  100 MB, so Revert works even once the maker's repository has dropped that version.

## Where each app comes from

| App            | Installed with                          | Revert goes back with                   | Hold                   |
| -------------- | --------------------------------------- | --------------------------------------- | ---------------------- |
| Obsidian       | Flatpak from Flathub, for your user     | the earlier Flathub build               | Flatpak's own mask     |
| VS Code        | apt, from Microsoft's repository        | the saved package                       | apt's own hold         |
| Claude Code    | apt, from Anthropic's repository        | the saved package                       | apt's own hold         |
| Claude Desktop | apt, from Anthropic's repository        | the saved package                       | apt's own hold         |
| OpenCode       | its installer from opencode.ai          | its installer, for the earlier version  | a note in `data/held`  |

- **apt sets up each repository the way its maker's install guide does:** the same file
  names, and the maker's signing key, checked against the fingerprint in `app.conf` before
  anything is added.
- **An apt hold works everywhere.** A held app also stays where it is through
  `sudo apt upgrade` and the system's updater. Without a hold, those update the apt apps
  too, from the same repository, but only Update here saves a revert point first.

## Notes per app

- **Obsidian** keeps its settings per vault, in each vault's `.obsidian/` folder, so they
  travel with the vault. Uninstall leaves your vaults and `~/.var/app/md.obsidian.Obsidian`
  alone. Flathub's listing can show an older version number than the build it serves
  (1.13.7 for 1.14.4, in October 2026), so Update names a Flathub update by its build date,
  and the menu shows the real version once it's installed.
- **VS Code** can't install its own updates on Linux; it only offers to download them.
  Installed from Microsoft's repository, it's updated here (or by `sudo apt upgrade`). To
  stop the offer, set **Update: Mode** to `none` in VS Code's settings. Its menu has two
  more entries: **backup_settings** saves `~/.config/Code/User` and the list of extensions
  into `apps/vscode/data/backups/`, and **restore_settings** puts a backup back. Close VS
  Code before restoring.
- **Claude Code** from Anthropic's own installer (`claude.ai/install.sh`) lives in
  `~/.local/bin` and updates itself. The menu shows that copy as [OTHER INSTALL], and
  Install replaces it with the apt package, which doesn't update itself. `~/.claude` and
  `~/.claude.json` (settings, sign-in, history) stay. The VS Code extension brings its own
  copy, which VS Code keeps up to date.
- **Claude Desktop** doesn't update itself on Linux; apt does. Its Cowork tab needs
  hardware virtualization; see
  [Anthropic's Linux page](https://code.claude.com/docs/en/desktop-linux).
- **OpenCode** updates itself when it starts, unless `"autoupdate": false` is in
  `~/.config/opencode/opencode.json`. Until then, a Hold or Revert lasts until its next
  start. Its installer adds `~/.opencode/bin` to your shell's PATH, so open a new terminal
  after installing it.

## Adding an app

Make a folder in `apps/` with an `app.conf`, and `manage.sh` lists it under APPS. Every
executable `*.sh` in the folder becomes an entry in its menu, like VS Code's
`backup_settings.sh`. The five `app.conf` files here are examples of each kind.

For every app:

| Setting    | What it is                                                                                  |
| ---------- | ------------------------------------------------------------------------------------------- |
| `NAME`     | The name the menu shows                                                                     |
| `ABOUT`    | One line about it, shown in its menu                                                         |
| `METHOD`   | `flatpak`, `apt` or `script`                                                                |
| `COMMAND`  | Optional: the command it puts on PATH, to notice a copy installed some other way            |
| `REPLACES` | Optional: where a copy installed some other way lives, as a list, e.g. `("$HOME/.local/bin/claude")`. Install removes these after installing. |
| `KEEPS`    | Optional: what Uninstall leaves in place, shown before it asks                              |

`METHOD=flatpak`:

| Setting              | What it is                                    |
| -------------------- | --------------------------------------------- |
| `FLATPAK_ID`         | The app's ID, such as `md.obsidian.Obsidian`  |
| `FLATPAK_REMOTE`     | Optional: the remote's name, `flathub` by default |
| `FLATPAK_REMOTE_URL` | Optional: where to add that remote from, Flathub's by default |

`METHOD=apt`. Take the values from the maker's install guide. Some packages manage their
source file themselves, and two files for one repository make apt fail.

| Setting               | What it is                                                                  |
| --------------------- | --------------------------------------------------------------------------- |
| `APT_PACKAGE`         | The package's name                                                          |
| `APT_URI`             | The repository's address                                                    |
| `APT_SUITE`           | Its suite, such as `stable`                                                 |
| `APT_COMPONENTS`      | Optional: its components, `main` by default                                 |
| `APT_ARCHS`           | Optional: the architectures it serves, such as `amd64,arm64`                |
| `APT_SOURCE_FILE`     | The source file to write. A `.list` file gets one line, a `.sources` file the newer format. |
| `APT_KEY_URL`         | Where its signing key is                                                    |
| `APT_KEY_FILE`        | Where to keep the key. A `.gpg` file stores it in binary, a `.asc` file as text. |
| `APT_KEY_FINGERPRINT` | The key's fingerprint. Install stops if the downloaded key doesn't match.   |

`METHOD=script`, for an app with neither:

| Setting                | What it is                                                                   |
| ---------------------- | ---------------------------------------------------------------------------- |
| `SCRIPT_INSTALLER_URL` | The maker's install script, which is downloaded and run with bash            |
| `SCRIPT_VERSION_ARG`   | Optional: the installer's option for one version, `--version` by default     |
| `SCRIPT_BIN`           | Where it installs the program. `SCRIPT_BIN --version` must print the version. |
| `SCRIPT_UNINSTALL`     | Optional: the arguments that make `SCRIPT_BIN` uninstall itself. Otherwise Uninstall deletes `SCRIPT_BIN`. |
| `GITHUB_REPO`          | Where its releases are, as `owner/name`. Update follows the newest one.      |

The same actions work from a terminal:

```bash
src/bash/app.sh obsidian update     # install, update, revert, hold, release, uninstall
```
