# Terminal installer

Install the QuillSail desktop app and a `quillsail` command with one line.

On macOS or Linux:

```sh
curl -fsSL https://quillsail.blog/install.sh | bash
```

On Windows, in PowerShell:

```powershell
irm https://quillsail.blog/install.ps1 | iex
```

Then start your publication with `quillsail instance`, open the desktop window with `quillsail desktop`, or open QuillSail from your Applications folder, Start menu or app menu. The installer needs no administrator rights and never touches your publications.

## What the installer does

1. **Works out your computer.** It finds your operating system and processor. On a Mac running the terminal under Rosetta, it still picks the Apple silicon build.
2. **Gets the release details.** It asks quillsail.blog for the newest release on your channel. The website takes the version, file size and SHA-256 checksum from QuillSail's [signed update feed](desktop-updates.md), after checking the feed's signatures.
3. **Downloads the app over HTTPS.** Downloads come from GitHub Releases.
4. **Checks the download.** The file's size and SHA-256 checksum must match the signed values exactly. If they don't, the installer stops and changes nothing.
5. **Unpacks it safely.** Every file must sit inside the app's own folder, and the app's version and platform must match. On macOS, the app's code signature is verified too.
6. **Installs it.** The new app is unpacked beside the destination, then moved into place in one step, replacing an earlier copy the installer finds there. A copy that's already up to date is left as it is.
7. **Adds the `quillsail` command** and, if needed, adds its folder to your `PATH`. On Linux it also adds QuillSail to your app menu, and on Windows to the Start menu.

## Where files go

| | macOS | Linux | Windows |
| --- | --- | --- | --- |
| App | `/Applications/QuillSail.app`, or `~/Applications` if you can't write to `/Applications` | `~/.local/opt/quillsail/QuillSail` | `%LOCALAPPDATA%\Programs\QuillSail` |
| Command | `~/.local/bin/quillsail` | `~/.local/bin/quillsail` | `%USERPROFILE%\.local\bin\quillsail.cmd` |
| Menu entry | Applications folder | `~/.local/share/applications/quillsail.desktop` | Start menu shortcut |
| Your publications | `~/Library/Application Support/QuillSail` | `~/.local/share/quillsail` | `%LOCALAPPDATA%\QuillSail` |

Publications always live outside the app, so installing, updating or removing the app never changes them.

When `~/.local/bin` isn't on your `PATH`, the installer adds one marked line to your shell's startup file: `~/.zshrc` for zsh, `~/.bash_profile` (macOS) or `~/.bashrc` (Linux) for bash, `~/.config/fish/conf.d/quillsail.fish` for fish, and `~/.profile` otherwise. Open a new terminal window afterwards. On Windows, the folder is added to your user `PATH`.

## Options

On macOS and Linux, pass options after `bash -s --`:

```sh
curl -fsSL https://quillsail.blog/install.sh | bash -s -- --channel stable --no-modify-path
```

| Option | Environment variable | What it does |
| --- | --- | --- |
| `--channel beta` or `--channel stable` | `QUILLSAIL_CHANNEL` | Release channel. The default is beta while QuillSail is in beta. |
| `--dir PATH` | `QUILLSAIL_INSTALL_DIR` | Folder for the app. |
| `--bin-dir PATH` | `QUILLSAIL_BIN_DIR` | Folder for the `quillsail` command. |
| `--no-modify-path` | `QUILLSAIL_NO_MODIFY_PATH=1` | Don't change your shell startup files or `PATH`. |
| `--uninstall` | `QUILLSAIL_UNINSTALL=1` (Windows) | Remove the app and the command. |
| `--help` | | Show the options. |

On Windows, set the environment variables before running the command:

```powershell
$env:QUILLSAIL_CHANNEL = 'stable'
irm https://quillsail.blog/install.ps1 | iex
```

## The `quillsail` command

The command does everything the desktop window does, so you can use QuillSail entirely from a terminal, including on a computer with no desktop. Run `quillsail` on its own to see every command.

| Command | What it does |
| --- | --- |
| `quillsail instance` | Start your publication in this terminal and print a link to its dashboard. |
| `quillsail instance --name NAME` | Start the publication with this name, creating it if it's new. |
| `quillsail instance --background` | Keep it running after this terminal closes. |
| `quillsail instance stop` | Stop it. Its content stays saved. |
| `quillsail desktop` | Open the desktop window, or bring it forward if it's already open. Closing the terminal doesn't close the window. |
| `quillsail update` | Download and install a signed update. Add `--check` to only check. |
| `quillsail --version` | Show the installed version. |

[Using QuillSail from the terminal](desktop.md#using-quillsail-from-the-terminal) covers the rest, and the [command-line reference](reference/cli.md) lists every command and option.

If you've also installed the Python package, keep the package's command and pass `--bin-dir` (or set `QUILLSAIL_BIN_DIR`) to put this one somewhere else. The installer never replaces a `quillsail` command it didn't create.

Older installers wrote a `quillsail` command that could only open the window, and it hid the output of anything else you ran. The app replaces that command the next time it starts. If yours is in a folder that isn't on your `PATH`, run the installer again.

## Updating

The app updates itself: choose **Check for updates** in the launcher, or run `quillsail update`. Running the installer again also installs the newest release, as long as QuillSail isn't running. Stop it first with **Quit QuillSail** in its window, or `quillsail instance stop --all`.

## Uninstalling

```sh
curl -fsSL https://quillsail.blog/install.sh | bash -s -- --uninstall
```

```powershell
$env:QUILLSAIL_UNINSTALL = '1'; irm https://quillsail.blog/install.ps1 | iex
```

This removes the app, the command and the menu entry. It keeps your publications; delete their folder (listed above) if you no longer need them. If the installer changed your shell startup file, remove the line marked *Added by the QuillSail installer* yourself.

## Read before you run

Piping a script into a shell runs it with your permissions, so it's reasonable to read it first:

```sh
curl -fsSL https://quillsail.blog/install.sh -o install.sh
less install.sh
bash install.sh
```

The scripts are short and commented, and their source is in the repository at [`website/quillsail_site/install/`](../website/quillsail_site/install/). They refuse to run as root, require HTTPS for every download, and stop at the first problem with nothing changed.

## How the download is trusted

The installer trusts two things: HTTPS to quillsail.blog and GitHub, and the release details the website publishes. The website only publishes downloads that appear in QuillSail's signed update feed, after verifying the feed with the same pinned keys the app uses. Each file is then checked against the signed SHA-256 checksum before anything is installed.

After installation, every update is verified by the app itself with [The Update Framework](desktop-updates.md), so later updates don't depend on the website at all.

These are beta builds. The Mac apps are signed with a Developer ID and notarized by Apple; the Windows app isn't code-signed yet. The signature checks above are separate from Apple's and Microsoft's publisher checks.

## For automation

The release details are available as JSON at `https://quillsail.blog/api/v1/releases/latest`, with an optional `?channel=stable`. Each download includes its version, file name, size, SHA-256 checksum and URL. `https://quillsail.blog/api/v1/releases/latest/macos-arm64.txt` returns the same details for one platform as plain `key value` lines, which is what the shell installer reads. Use one of `macos-arm64`, `macos-x86_64`, `windows-x86_64`, `linux-x86_64` or `server`.

`https://quillsail.blog/download/PLATFORM` always redirects to the newest download for that platform.

## Troubleshooting

**"QuillSail is running."** Choose **Quit QuillSail** in its window, or run `quillsail instance stop --all`. Then run the installer again.

**`quillsail: command not found`.** Open a new terminal window so it reads the updated `PATH`. If you used `--no-modify-path`, add `~/.local/bin` to your `PATH` yourself.

**"The download's SHA-256 checksum doesn't match."** The file was corrupted or changed on the way. Nothing was installed. Try again later. If it keeps happening, [report it](https://github.com/DoobaDigital/QuillSail/issues).

**Linux: "No desktop session was found."** The desktop window needs a graphical desktop, but `quillsail instance` doesn't. To run a public site on a server, use [Docker Compose or the Python package](installation.md) instead.

**Linux: "The desktop app needs glibc 2.35 or newer."** The Linux app is built on Ubuntu 22.04. On older or musl-based systems, use the Python package.

**Linux: the desktop window won't open.** A minimal system may be missing desktop libraries. See [using the app](desktop.md#using-the-app) for the list.
