# Desktop launcher

Open **QuillSail** to start a local publication and open its dashboard in your browser. The packaged app includes Python and its dependencies. You do not need a terminal, Docker, or a configuration file to use it.

On the first launch, enter your publication name, choose Newsletter / Blog / Blog + newsletter, and create your administrator account. The launcher authorizes this first setup automatically; there is no setup code to retrieve. Finishing the form signs you into the dashboard. Future launches reopen your publication; your remembered browser session keeps you signed in, or you can sign in with your account.

## Using the app

Install it with one command using the [terminal installer](install-script.md), or download the beta from [quillsail.blog/download](https://quillsail.blog/download) or the [GitHub release](https://github.com/DoobaDigital/QuillSail/releases/tag/v1.10.0). Four separate downloads cover Apple Silicon Macs (`macos-arm64`), Intel Macs (`macos-x86_64`), 64-bit Windows (`windows-x86_64`), and 64-bit Linux (`linux-x86_64`). `SHA256SUMS.txt` contains the archive hashes; `desktop-builds.json` records the source commit and native verification results.

New releases offer graphical installers, matching your CPU architecture:

- **macOS:** open the `.dmg`, drag **QuillSail.app** onto the **Applications** shortcut, eject the image, then open QuillSail from Applications. Choose Apple Silicon or Intel for your Mac.
- **Windows x64:** open `-setup.exe`, follow the setup wizard and choose **Launch QuillSail**. Installation is per user under `%LOCALAPPDATA%\Programs\QuillSail`, with a Start menu entry and an optional desktop shortcut. No administrator account is required.
- **Linux x86-64:** open the `.deb` with your desktop software installer on Ubuntu 22.04 or a compatible Debian-based distribution, install it, then open QuillSail from the application menu. Some desktops require a package-installer application first. Other distributions can use the terminal installer or updater archive.

Existing releases retain their ZIP/tar.gz downloads: extract them, move the Mac app to Applications, or keep the Windows/Linux application folder together. The website uses these archives until a release with signed graphical installers is available. Terminal installation remains an alternative.

Quit QuillSail before reinstalling or uninstalling. On macOS, remove the app from Applications; on Windows, use Installed apps → QuillSail → Uninstall; on Linux, remove `quillsail-desktop` in your software manager. Removing or replacing the application keeps publication data and the instance registry. Delete publication files only through the explicit instance deletion controls, after making a backup. Installing over an existing application preserves its separate data folders.

The Linux package installs into `/opt/QuillSail`, with menu and icon files under `/usr/share`. Use your software installer to upgrade or reinstall it: the app updater cannot replace this administrator-owned directory. Per-user terminal installations continue to support in-app updates.

Linux builds use Ubuntu 22.04 and require a desktop environment. On a minimal Ubuntu installation, missing Qt/X11 libraries can be installed with `sudo apt-get install libegl1 libopengl0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libxcb-render-util0 libxcb-xfixes0`. Other distributions need the equivalent packages. Windows builds target x64 Windows; Windows ARM and 32-bit systems are not included.

The launcher starts automatically. **Open dashboard** reopens your browser, **Stop** finishes background work and stops the local website, and **Start** starts it again. **View logs** opens the private local log, while **Open data folder** shows the files to back up. The launcher uses an available port on `127.0.0.1`, remembers it, and stays accessible only on your computer.

The launcher opens in light mode. Under **Appearance**, choose **Dark**, or **Automatic** to follow your system's light or dark setting. Your choice is remembered for the next launch, and the first-time setup page in your browser uses the same appearance.

Email initially stays in local `.eml` files. Configure a sender in Settings → Email when you want actual delivery. The dashboard stays private on your computer. Use [Domains and launch](hosting.md) to connect a public address or enable the optional offline fallback. [Server installation](installation.md) covers an always-running website and email worker. Connecting Gmail/Outlook still needs the provider registration described in [email connectors](email-connectors.md).

## Data and updates

In builds with update support, choose **Check for updates**, then **Install QuillSail…**. Select the Stable or Beta channel; Beta is selected initially while QuillSail is in beta. Installing an update downloads and verifies it, finishes background work, closes the app, replaces the application, and restarts it. Checks run only when requested and updates require confirmation. Close other QuillSail windows for that application before updating. Read-only installations and apps running from a translocated Mac download must be moved to a writable application folder first; the updater does not request administrator access.

The equivalent commands are:

```sh
quillsail update --desktop --check
quillsail update --app /Applications/QuillSail.app
quillsail update --app /path/to/QuillSail --channel stable --yes
```

`--app` names the complete desktop application folder. A command running outside the desktop bundle installs synchronously; reopen the app afterwards. The packaged executable also accepts `--check-updates` or `--update --yes`. Without `--app` or `--desktop`, the CLI manages a registered server; see [server updates](server-updates.md). `quillsail upgrade` remains the database-migration command.

Versions before updater support must be replaced manually once using a newer desktop download. Committing a change to GitHub does not create a new downloadable version. A maintainer must publish a tested release and its signed update metadata before clients can receive it.

The app keeps its publication outside the application bundle, so replacing the app preserves your account, settings, secret key, content and uploaded files:

| System | Default data folder |
| --- | --- |
| macOS | `~/Library/Application Support/QuillSail` |
| Windows | `%LOCALAPPDATA%\QuillSail` |
| Linux | `$XDG_DATA_HOME/quillsail`, or `~/.local/share/quillsail` |

Quit QuillSail before backing up or replacing the app. Copy the complete data folder to protected storage. Before a schema upgrade, the launcher automatically saves a consistent SQLite database backup, configuration and uploaded files under `backups/`. If startup reports an upgrade failure, preserve that backup and consult [maintenance](maintenance.md) before retrying or restoring an older app. Do not restore pending mail jobs into an active sender without reviewing them.

Each publication has a separate runtime and folder lock. Repeated starts cannot create a second worker for the same folder. Desktop configuration is isolated from server environment variables and existing CLI/server installations. Advanced users can select a separate empty folder with `quillsail desktop --data-dir PATH`.

An OS lock prevents replacing a desktop application while its launcher is open. The verified archive and previous application remain in a private `.quillsail-update-*` folder beside the application. If replacement fails, the helper restores the previous application and records the error for the next launch. Application replacement does not restore or alter publication files. After database migrations have run, recovering an older version still requires the matching publication backup described in [maintenance](maintenance.md).

See [maintaining signed updates](desktop-updates.md) for trust-root setup, signing keys, feed renewal and fork configuration. There is no unsigned update fallback.

## Building a bundle

Build on the target operating system and CPU; these are native bundles, not cross-compilations. From a clean checkout, build/install the wheel and the optional desktop dependencies in a virtual environment:

```sh
python -m pip install build
python -m build --wheel
python -m pip install 'dist/copydesk-VERSION-py3-none-any.whl[desktop-build]'
python scripts/build_desktop.py
```

Replace VERSION with the built version. Bundles and graphical installers appear in `dist/desktop/`. macOS needs Xcode command-line tools (`hdiutil`, `ditto`, `codesign`); Windows needs Inno Setup 6 (`ISCC`); Linux needs `dpkg` and `desktop-file-utils`. The build includes package resources, Python, the native Qt libraries and dependency license files. Installer checks mount and copy the DMG app, silently install/reinstall/uninstall the Windows setup, or install/reinstall/remove the Linux package in an isolated dpkg root. They run the installed app with disposable data. It runs disposable browser setup/restart and native GUI start/stop/restart checks using the bundled executable; it sends no mail. Run the checks independently with `QuillSail --smoke-test` and `QuillSail --smoke-test-gui`. For source development, install `.[desktop]` and run `quillsail desktop` or `quillsail-desktop`.

On Intel macOS, install the build dependencies in a clean environment with `OPENSSL_STATIC=1 python -m pip install --no-cache-dir 'dist/copydesk-VERSION-py3-none-any.whl[desktop-build]'`. This keeps a source-built cryptography binding independent of Python's OpenSSL library. The build rejects dynamically linked macOS bindings, which can collide when bundled. See [Cryptography's installation guide](https://cryptography.io/en/latest/installation/).

The **Desktop bundles** GitHub Actions workflow explicitly builds all four targets on native runners and verifies the server wheel/source. Pull requests and ordinary manual runs only save workflow artifacts. A maintainer can run it on `main` with **publish** enabled to publish a beta after every target passes. It validates source commits and hashes, stages all assets in a draft, then publishes the complete release. A failed upload leaves a resumable draft. Published versions cannot be overwritten by the script. This workflow publishes downloadable desktop bundles and server packages; it does not publish containers or packages to a registry.

### Mac signing and notarization

Released Mac apps are signed with a Developer ID and notarized by Apple, so macOS opens them without asking. On Mac runners, the **Desktop bundles** workflow signs every binary in the app with the hardened runtime and a secure timestamp, from the innermost files out. Manual runs then notarize and staple the app before creating its updater archive, and sign, notarize and staple the DMG. Each upload to Apple is limited to 10 minutes and tried up to three times. Status checks are limited to 2 minutes and repeated on the same submission. If Apple hasn't finished a file within 30 minutes, the build fails and names the submission. Pull request runs sign without notarizing. Publishing refuses Mac builds that aren't notarized, so an expired Apple Developer membership or certificate stops a release instead of shipping an unsigned app.

The workflow reads the certificate and notarization login from five repository secrets: `MACOS_CERTIFICATE_P12` (a base64-encoded Developer ID Application certificate and private key), `MACOS_CERTIFICATE_PASSWORD`, `APPLE_ID`, `APPLE_APP_PASSWORD` (an app-specific password) and `APPLE_TEAM_ID`. It imports them into a temporary keychain that is deleted after the build. They never enter the repository, the app or the logs.

Local builds and pull requests from forks have no certificate, so they stay ad-hoc signed and macOS asks before opening them. To sign a local build, set `QUILLSAIL_MACOS_IDENTITY` to the name of a Developer ID Application identity in your keychain. To notarize it as well, also set `QUILLSAIL_NOTARY_PROFILE` to a profile saved with `xcrun notarytool store-credentials`.

The Windows setup executable is unsigned, so SmartScreen may warn before it runs. Linux packages are verified through the signed QuillSail feed rather than a distribution repository signature.

The launcher uses [Qt for Python](https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html) and [PyInstaller](https://pyinstaller.org/en/stable/usage.html). Retain the bundled dependency licenses when redistributing; their licenses remain separate from QuillSail's MIT license.

## Multiple publications

Starting with 1.9.1, **Publication instance** selects the publication controlled by the launcher. Choose **New instance…**, name it, and finish the usual setup in your browser. **Add existing…** registers an existing desktop data folder without moving or copying it. **Refresh** picks up instances created by the CLI.

Start each desired instance with **Start**. Switching the selector keeps the others running; **Stop** stops only the selected publication. Each instance has its own database, configuration, account setup, browser cookie, uploads, email queue and available loopback port. A second launcher cannot start another worker for the same folder. If an instance is running in another launcher or terminal, you can open its dashboard here; stop it from the launcher or terminal that started it.

Closing the window keeps every instance running in the background, like other menu bar apps. QuillSail stays in the macOS menu bar or the Windows and Linux system tray; choose **Open QuillSail** there, click its Dock icon, or open the app again to bring the window back. To stop the instances, quit QuillSail: use the **Quit QuillSail** button, **⌘Q** (Ctrl+Q on Windows and Linux), the menu bar or tray icon, or run `quillsail quit` in a terminal. Quitting finishes background work first, and your content stays saved. If your Linux desktop has no system tray, closing the window quits instead. Installing an update also stops the launcher's instances before replacing the shared application. Publication folders and the instance list remain saved; reopen and start the publications you want after the update. Stop CLI-launched instances before replacing the desktop application.

Your original publication remains **Default publication**, in its original folder. Additional instances and their private registry live beside that folder in `QuillSail-instances` on macOS/Windows or `quillsail-instances` on Linux. `QUILLSAIL_INSTANCE_HOME` can select another registry/managed-publications directory. Back up the registry and every registered publication folder; added external folders are referenced, not copied. The registry contains display names and paths, not provider credentials.

The CLI uses the same instance list:

```sh
quillsail instance create "Student Blog"
quillsail instance create "Community News"
quillsail instance list
quillsail instance run student-blog community-news
```

The last command starts both websites and background workers, prints their local setup/dashboard links, and opens them in the browser. Leave the terminal running; **Ctrl+C** stops all instances started by that command. `quillsail quit` quits the desktop app and the instances it started; it does not stop instances running in a terminal. Use `--no-browser` to print links only or `--no-worker` to leave queued jobs unprocessed. You can also run instances in separate terminals. `instance list --json` reports their paths and currently running addresses.

Use `quillsail instance add NAME /path/to/publication` for an existing desktop publication. Named instances are also available to maintenance commands and the desktop launcher:

```sh
quillsail --instance student-blog jobs list
quillsail --instance student-blog check
quillsail --instance student-blog export ./student-blog-backup.json
quillsail --instance student-blog desktop
```

To delete any instance, including **Default publication**, choose **Delete instance…** in the launcher. If it is running here, confirming **Stop and delete** finishes background work and stops it before removing it. Cancelling leaves it running. Instances running in another launcher or terminal must be stopped there first; the button explains this when unavailable.

By default, its files stay saved so you can register the folder again with **Add existing…**. Select **Permanently delete publication files** to erase the folder, including content, subscribers, credentials and uploads. This cannot be undone; back up anything you want to keep first.

After deleting the last instance, the launcher shows **Create or add an instance**, with **New instance…** and **Add existing…** available. This empty list stays saved when you quit and reopen QuillSail. If other instances remain, the launcher selects one and keeps any others running.

The terminal provides the same choices and asks for confirmation:

```sh
quillsail instance delete student-blog
quillsail instance delete student-blog --delete-data
quillsail instance delete default
```

The first command keeps the files; the second permanently deletes the publication folder, including folders registered with `instance add`. The third removes Default publication, keeping its files. Use `--yes` to skip confirmation. Stop the selected instance in its launcher or terminal before deleting it from the CLI; running instances are refused.

**View logs** opens the launcher's log in the instance registry folder. The log stays available when a publication is deleted.

Choose either `--instance` or an explicit `--config`. Named instances ignore server configuration environment overrides, so a local command cannot accidentally target a server database. `init` creates a manually configured installation; use `instance create` for a named local publication. Software updates apply to the shared installation, so run desktop updates without `--instance`. Production deployments can continue to use separate configuration files and supervised web/worker processes, as described in [installation](installation.md).
