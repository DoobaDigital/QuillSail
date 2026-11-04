#!/usr/bin/env bash
# QuillSail installer for macOS and Linux.
#
#   curl -fsSL __QUILLSAIL_SITE_URL__/install.sh | bash
#
# Installs the QuillSail desktop app and a `quillsail` command for your terminal.
# Each download is checked against the size and SHA-256 checksum listed in
# QuillSail's signed release feed before anything is installed. Nothing here
# needs administrator rights, and your publications are never touched.
#
# Options go after `bash -s --`, for example:
#
#   curl -fsSL __QUILLSAIL_SITE_URL__/install.sh | bash -s -- --channel stable
#
#   --channel beta|stable  Release channel. Default: beta, while QuillSail is in beta.
#   --dir PATH             Folder for the app. Default: /Applications, or ~/Applications
#                          if you can't write there, on macOS; ~/.local/opt/quillsail on Linux.
#   --bin-dir PATH         Folder for the quillsail command. Default: ~/.local/bin
#   --no-modify-path       Don't add the command's folder to your shell profile.
#   --uninstall            Remove the app and the command. Your publications are kept.
#   -h, --help             Show this help.
#
# The same settings can come from QUILLSAIL_CHANNEL, QUILLSAIL_INSTALL_DIR,
# QUILLSAIL_BIN_DIR and QUILLSAIL_NO_MODIFY_PATH=1.

set -eu

# Everything runs from main(), at the very end, so a partly downloaded script does nothing.

SITE="__QUILLSAIL_SITE_URL__"
MARKER_LINE="# Installed by the QuillSail installer."

CHANNEL="${QUILLSAIL_CHANNEL:-beta}"
INSTALL_DIR="${QUILLSAIL_INSTALL_DIR:-}"
BIN_DIR="${QUILLSAIL_BIN_DIR:-$HOME/.local/bin}"
NO_MODIFY_PATH="${QUILLSAIL_NO_MODIFY_PATH:-0}"
UNINSTALL=0

OS=""
TARGET=""
VERSION=""
ARCHIVE=""
SIZE=""
SHA256=""
URL=""
WORK=""
STAGED=""
COMMAND_STATUS=""
PROFILE_CHANGED=""

if [ -t 1 ]; then
  BOLD="$(printf '\033[1m')"
  RESET="$(printf '\033[0m')"
else
  BOLD=""
  RESET=""
fi

say() { printf '%s\n' "$*"; }
step() { printf '%s›%s %s\n' "$BOLD" "$RESET" "$*"; }
warn() { printf 'Note: %s\n' "$*" >&2; }
fail() {
  printf '\nQuillSail was not installed. %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'HELP'
Install the QuillSail desktop app and a `quillsail` command for your terminal.

  curl -fsSL __QUILLSAIL_SITE_URL__/install.sh | bash -s -- [options]

  --channel beta|stable  Release channel. Default: beta, while QuillSail is in beta.
  --dir PATH             Folder for the app.
  --bin-dir PATH         Folder for the quillsail command. Default: ~/.local/bin
  --no-modify-path       Don't add the command's folder to your shell profile.
  --uninstall            Remove the app and the command. Your publications are kept.
  -h, --help             Show this help.
HELP
}

cleanup() {
  if [ -n "$STAGED" ] && [ -e "$STAGED" ]; then rm -rf "$STAGED"; fi
  if [ -n "$WORK" ] && [ -d "$WORK" ]; then rm -rf "$WORK"; fi
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --channel) [ "$#" -ge 2 ] || fail "--channel needs beta or stable."; CHANNEL="$2"; shift 2 ;;
      --channel=*) CHANNEL="${1#*=}"; shift ;;
      --dir) [ "$#" -ge 2 ] || fail "--dir needs a folder."; INSTALL_DIR="$2"; shift 2 ;;
      --dir=*) INSTALL_DIR="${1#*=}"; shift ;;
      --bin-dir) [ "$#" -ge 2 ] || fail "--bin-dir needs a folder."; BIN_DIR="$2"; shift 2 ;;
      --bin-dir=*) BIN_DIR="${1#*=}"; shift ;;
      --no-modify-path) NO_MODIFY_PATH=1; shift ;;
      --uninstall) UNINSTALL=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) fail "Unknown option: $1. Use --help to see the options." ;;
    esac
  done
  case "$CHANNEL" in
    beta|stable) ;;
    *) fail "Choose the beta or stable channel, not \"$CHANNEL\"." ;;
  esac
}

# --- where things go ---------------------------------------------------------------------------------

detect_platform() {
  case "$(uname -s)" in
    Darwin) OS=macos ;;
    Linux) OS=linux ;;
    MINGW*|MSYS*|CYGWIN*) fail "On Windows, run this in PowerShell instead: irm __QUILLSAIL_SITE_URL__/install.ps1 | iex" ;;
    *) fail "QuillSail's desktop app runs on macOS, Windows and Linux. To run it on a server, see __QUILLSAIL_SITE_URL__/download" ;;
  esac
  machine="$(uname -m)"
  if [ "$OS" = macos ]; then
    # A Terminal running under Rosetta reports x86_64 on Apple silicon.
    if [ "$machine" = x86_64 ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = 1 ]; then
      machine=arm64
    fi
    case "$machine" in
      arm64) TARGET=macos-arm64 ;;
      x86_64) TARGET=macos-x86_64 ;;
      *) fail "This Mac's processor ($machine) isn't supported." ;;
    esac
  else
    case "$machine" in
      x86_64|amd64) TARGET=linux-x86_64 ;;
      aarch64|arm64) fail "There's no desktop app for ARM Linux yet. Run QuillSail as a server instead: __QUILLSAIL_SITE_URL__/download" ;;
      *) fail "This computer's processor ($machine) isn't supported." ;;
    esac
  fi
}

choose_folders() {
  if [ -z "$INSTALL_DIR" ]; then
    if [ "$OS" = macos ]; then
      if [ -w /Applications ]; then INSTALL_DIR=/Applications; else INSTALL_DIR="$HOME/Applications"; fi
    else
      INSTALL_DIR="$HOME/.local/opt/quillsail"
    fi
  fi
  case "$INSTALL_DIR$BIN_DIR" in
    *"'"*|*'"'*|*'\'*) fail "Choose folders without quote marks or backslashes in their names." ;;
  esac
  case "$INSTALL_DIR" in /*) ;; *) INSTALL_DIR="$(pwd)/$INSTALL_DIR" ;; esac
  case "$BIN_DIR" in /*) ;; *) BIN_DIR="$(pwd)/$BIN_DIR" ;; esac
  if [ "$OS" = macos ]; then
    APP="$INSTALL_DIR/QuillSail.app"
    EXECUTABLE="$APP/Contents/MacOS/QuillSail"
    MARKER="$APP/Contents/Resources/quillsail-install.json"
    DATA_DIR="$HOME/Library/Application Support/QuillSail"
  else
    APP="$INSTALL_DIR/QuillSail"
    EXECUTABLE="$APP/QuillSail"
    MARKER="$APP/quillsail-install.json"
    DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/quillsail"
    APPLICATIONS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
  fi
  COMMAND="$BIN_DIR/quillsail"
}

# --- checks ------------------------------------------------------------------------------------------

need() {
  command -v "$1" >/dev/null 2>&1 || fail "$2"
}

check_requirements() {
  if [ "$(id -u)" = 0 ]; then
    fail "Run the installer as yourself, without sudo. It installs QuillSail for your account."
  fi
  if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    fail "This installer needs curl or wget."
  fi
  if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1 && ! command -v openssl >/dev/null 2>&1; then
    fail "This installer needs sha256sum, shasum or openssl to check the download."
  fi
  if [ "$OS" = macos ]; then
    need ditto "This installer needs macOS's ditto command."
    need zipinfo "This installer needs macOS's zipinfo command."
  else
    need tar "This installer needs tar."
    check_glibc
    if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
      warn "No desktop session was found, so the desktop window won't open here. Run QuillSail from this terminal with: quillsail instance"
    fi
  fi
  case "$SITE" in
    https://*) ;;
    http://127.0.0.1:*|http://localhost:*|http://127.0.0.1|http://localhost) ;;  # Local testing only.
    *) fail "The installer must come from an https:// address." ;;
  esac
}

check_glibc() {
  # The Linux app is built on Ubuntu 22.04 and needs glibc 2.35 or newer.
  version="$( (ldd --version 2>&1 || true) | head -n 1)"
  case "$version" in
    *musl*) fail "This Linux uses musl, and the desktop app needs glibc. Run QuillSail as a server instead: __QUILLSAIL_SITE_URL__/download" ;;
  esac
  number="$(printf '%s' "$version" | grep -oE '[0-9]+\.[0-9]+$' || true)"
  if [ -n "$number" ]; then
    major="${number%%.*}"
    minor="${number#*.}"
    if [ "$major" -lt 2 ] || { [ "$major" -eq 2 ] && [ "$minor" -lt 35 ]; }; then
      fail "The desktop app needs glibc 2.35 or newer (Ubuntu 22.04 or later). This system has $number."
    fi
  fi
}

# --- downloading -------------------------------------------------------------------------------------

fetch() {
  # fetch URL FILE [progress]
  if command -v curl >/dev/null 2>&1; then
    set -- "$1" "$2" "${3:-}"
    if [ "${SITE#https://}" != "$SITE" ]; then
      proto="--proto =https --proto-redir =https"
    else
      proto=""
    fi
    if [ "$3" = progress ] && [ -t 2 ]; then
      # shellcheck disable=SC2086
      curl --fail --location --retry 3 --connect-timeout 20 --progress-bar $proto --output "$2" "$1"
    else
      # shellcheck disable=SC2086
      curl --fail --location --retry 3 --connect-timeout 20 --silent --show-error $proto --output "$2" "$1"
    fi
  else
    if [ "${SITE#https://}" != "$SITE" ]; then https="--https-only"; else https=""; fi
    # shellcheck disable=SC2086
    wget --quiet --tries=3 --timeout=30 $https --output-document="$2" "$1"
  fi
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    openssl dgst -sha256 "$1" | awk '{print $NF}'
  fi
}

read_release() {
  manifest="$WORK/release.txt"
  if ! fetch "$SITE/api/v1/releases/latest/$TARGET.txt?channel=$CHANNEL" "$manifest"; then
    fail "Release details couldn't be downloaded from $SITE. Check your connection and try again in a few minutes."
  fi
  while read -r key value; do
    case "$key" in
      version) VERSION="$value" ;;
      archive) ARCHIVE="$value" ;;
      size) SIZE="$value" ;;
      sha256) SHA256="$value" ;;
      url) URL="$value" ;;
      error) fail "$value" ;;
    esac
  done < "$manifest"

  version_pattern='^[0-9]+\.[0-9]+\.[0-9]+$'
  digest_pattern='^[0-9a-f]{64}$'
  size_pattern='^[1-9][0-9]*$'
  if [ "$OS" = macos ]; then suffix=zip; else suffix=tar.gz; fi
  if ! [[ "$VERSION" =~ $version_pattern ]] || ! [[ "$SHA256" =~ $digest_pattern ]] \
      || ! [[ "$SIZE" =~ $size_pattern ]] || [ "$ARCHIVE" != "QuillSail-$VERSION-$TARGET.$suffix" ]; then
    fail "The release details from $SITE weren't in the expected format."
  fi
  case "$URL" in
    https://*) ;;
    http://127.0.0.1:*|http://localhost:*) [ "${SITE#https://}" = "$SITE" ] || fail "The download address must use https://." ;;
    *) fail "The download address must use https://." ;;
  esac
}

installed_version() {
  if [ -f "$MARKER" ]; then
    sed -n 's/.*"version": *"\([0-9.]*\)".*/\1/p' "$MARKER" | head -n 1
  fi
}

check_running() {
  if command -v pgrep >/dev/null 2>&1 && pgrep -f "$EXECUTABLE" >/dev/null 2>&1; then
    fail "QuillSail is running. Choose Quit QuillSail in its window, or run quillsail instance stop --all. Then run the installer again."
  fi
}

download_and_check() {
  archive="$WORK/$ARCHIVE"
  step "Downloading QuillSail $VERSION for $(describe_target)…"
  if ! fetch "$URL" "$archive" progress; then
    fail "The download didn't finish. Check your connection and try again."
  fi
  step "Checking the download…"
  actual_size="$(wc -c < "$archive" | tr -d ' ')"
  if [ "$actual_size" != "$SIZE" ]; then
    fail "The download is $actual_size bytes, but the signed release lists $SIZE. Nothing was changed."
  fi
  actual="$(sha256_of "$archive")"
  if [ "$actual" != "$SHA256" ]; then
    fail "The download's SHA-256 checksum doesn't match the signed release. Nothing was changed."
  fi
}

check_archive_paths() {
  # Every file must sit inside the app's own folder.
  if [ "$OS" = macos ]; then
    names="$(zipinfo -1 "$1")" || fail "The download couldn't be read as a zip file."
    top="QuillSail.app"
  else
    names="$(tar -tzf "$1")" || fail "The download couldn't be read as a tar.gz file."
    top="QuillSail"
  fi
  # ditto keeps macOS metadata in __MACOSX/, which the app's own updater also skips.
  bad="$(printf '%s\n' "$names" | awk -v top="$top" -v os="$OS" '
    $0 == "" { next }
    os == "macos" && $0 ~ /^__MACOSX(\/|$)/ && $0 !~ /(^|\/)\.\.(\/|$)/ { next }
    index($0, top "/") != 1 && $0 != top || $0 ~ /(^|\/)\.\.(\/|$)/ { print; exit }')"
  if [ -n "$bad" ]; then
    fail "The download contains an unexpected path ($bad). Nothing was changed."
  fi
}

describe_target() {
  case "$TARGET" in
    macos-arm64) say "Macs with Apple silicon" ;;
    macos-x86_64) say "Intel Macs" ;;
    linux-x86_64) say "64-bit Linux" ;;
  esac
}

# --- installing --------------------------------------------------------------------------------------

install_app() {
  mkdir -p "$INSTALL_DIR" || fail "$INSTALL_DIR couldn't be created."
  [ -w "$INSTALL_DIR" ] || fail "You can't write to $INSTALL_DIR. Choose another folder with --dir."
  if [ -e "$APP" ] && [ ! -f "$MARKER" ]; then
    fail "$APP already exists and isn't a QuillSail installation. Move it, or choose another folder with --dir."
  fi
  check_archive_paths "$archive"
  # Unpack beside the destination, so the final step is a rename on one disk.
  STAGED="$INSTALL_DIR/.quillsail-install-$$"
  rm -rf "$STAGED"
  mkdir -p "$STAGED"
  step "Installing to $APP…"
  if [ "$OS" = macos ]; then
    ditto -x -k "$archive" "$STAGED" || fail "The download couldn't be unpacked."
    new="$STAGED/QuillSail.app"
    marker="$new/Contents/Resources/quillsail-install.json"
  else
    tar -xzf "$archive" -C "$STAGED" --no-same-owner || fail "The download couldn't be unpacked."
    new="$STAGED/QuillSail"
    marker="$new/quillsail-install.json"
  fi
  if ! grep -q "\"version\": \"$VERSION\"" "$marker" 2>/dev/null || ! grep -q "\"target\": \"$TARGET\"" "$marker" 2>/dev/null; then
    fail "The unpacked app doesn't match QuillSail $VERSION for this computer. Nothing was changed."
  fi
  if [ -n "$(find "$new" -type l -lname '/*' -print 2>/dev/null | head -n 1)" ]; then
    fail "The unpacked app contains a link outside its folder. Nothing was changed."
  fi
  if [ "$OS" = macos ] && command -v codesign >/dev/null 2>&1; then
    codesign --verify --deep --strict "$new" >/dev/null 2>&1 || fail "The app's code signature doesn't verify. Nothing was changed."
  fi
  previous=""
  if [ -e "$APP" ]; then
    previous="$STAGED/previous"
    mv "$APP" "$previous" || fail "The installed app couldn't be moved aside."
  fi
  if ! mv "$new" "$APP"; then
    if [ -n "$previous" ]; then mv "$previous" "$APP" || true; fi
    fail "The new app couldn't be moved into place. The previous version was kept."
  fi
}

write_command() {
  mkdir -p "$BIN_DIR" 2>/dev/null || true
  if [ -e "$COMMAND" ] && ! grep -qF "$MARKER_LINE" "$COMMAND" 2>/dev/null; then
    COMMAND_STATUS=kept
    return
  fi
  if ! [ -w "$BIN_DIR" ]; then
    COMMAND_STATUS=unwritable
    return
  fi
  new_command="$COMMAND.new-$$"
  {
    printf '#!/bin/sh\n'
    printf '%s Runs the quillsail command from the app.\n' "$MARKER_LINE"
    printf '# Remove it with: curl -fsSL %s/install.sh | bash -s -- --uninstall\n' "$SITE"
    printf "executable='%s'\n" "$EXECUTABLE"
    printf '%s\n' 'exec "$executable" cli "$@"'
  } > "$new_command"
  chmod 755 "$new_command"
  mv "$new_command" "$COMMAND"
  COMMAND_STATUS=written
}

write_desktop_entry() {
  # Linux only: a menu entry and icon, outside the app folder so updates keep them.
  mkdir -p "$APPLICATIONS" "$ICONS" 2>/dev/null || return 0
  icon="$APP/_internal/copydesk/static/brand/quillsail.svg"
  icon_name="QuillSail"
  if [ -f "$icon" ] && cp "$icon" "$ICONS/quillsail.svg" 2>/dev/null; then icon_name="quillsail"; fi
  {
    printf '[Desktop Entry]\n'
    printf 'Type=Application\n'
    printf 'Name=QuillSail\n'
    printf 'Comment=Blogs and newsletters where readers write\n'
    printf 'Exec="%s"\n' "$EXECUTABLE"
    printf 'Icon=%s\n' "$icon_name"
    printf 'Terminal=false\n'
    printf 'Categories=Office;Network;\n'
    printf 'X-QuillSail-Installer=true\n'
  } > "$APPLICATIONS/quillsail.desktop"
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS" >/dev/null 2>&1 || true
  fi
}

shell_profile() {
  case "$(basename "${SHELL:-sh}")" in
    zsh) printf '%s\n' "${ZDOTDIR:-$HOME}/.zshrc" ;;
    bash) if [ "$OS" = macos ]; then printf '%s\n' "$HOME/.bash_profile"; else printf '%s\n' "$HOME/.bashrc"; fi ;;
    fish) printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/quillsail.fish" ;;
    *) printf '%s\n' "$HOME/.profile" ;;
  esac
}

ensure_path() {
  case ":$PATH:" in
    *":$BIN_DIR:"*) return 0 ;;
  esac
  [ "$NO_MODIFY_PATH" = 1 ] && return 0
  [ "$COMMAND_STATUS" = written ] || return 0
  shown="$BIN_DIR"
  case "$BIN_DIR" in "$HOME"/*) shown="\$HOME/${BIN_DIR#"$HOME"/}" ;; esac
  profile="$(shell_profile)"
  case "$profile" in
    *.fish) line="fish_add_path \"$shown\"" ;;
    *) line="export PATH=\"$shown:\$PATH\"" ;;
  esac
  if [ -f "$profile" ] && grep -qF "$line" "$profile"; then return 0; fi
  mkdir -p "$(dirname "$profile")" 2>/dev/null || true
  if printf '\n# Added by the QuillSail installer\n%s\n' "$line" >> "$profile" 2>/dev/null; then
    PROFILE_CHANGED="$profile"
  fi
}

# --- results -----------------------------------------------------------------------------------------

summarize() {
  say ""
  say "${BOLD}QuillSail $VERSION is installed.${RESET}"
  say "  App      $APP"
  case "$COMMAND_STATUS" in
    written) say "  Command  $COMMAND" ;;
    kept) warn "$COMMAND already exists and wasn't made by this installer, so it was left alone." ;;
    unwritable) warn "The quillsail command wasn't added because $BIN_DIR can't be written to." ;;
  esac
  say ""
  if [ -n "$PROFILE_CHANGED" ]; then
    say "Added $BIN_DIR to your PATH in $PROFILE_CHANGED."
    say "Open a new terminal window, then start your publication: quillsail instance"
  elif [ "$COMMAND_STATUS" = written ]; then
    case ":$PATH:" in
      *":$BIN_DIR:"*) say "Start your publication: quillsail instance" ;;
      *) say "Add $BIN_DIR to your PATH to run quillsail, or use: $COMMAND instance" ;;
    esac
  fi
  if [ "$COMMAND_STATUS" = written ]; then
    say "Open the desktop window: quillsail desktop"
    say "See every command: quillsail"
  fi
  if [ "$OS" = macos ]; then
    say "You can also open QuillSail from your Applications folder."
  else
    say "You can also open QuillSail from your applications menu."
  fi
  say "Your publications are kept in $DATA_DIR."
}

uninstall() {
  choose_folders
  removed=""
  if [ -f "$MARKER" ]; then
    check_running
    rm -rf "$APP"
    removed="yes"
    say "Removed $APP"
  elif [ -e "$APP" ]; then
    warn "$APP isn't a QuillSail installation, so it was left alone."
  fi
  if [ -f "$COMMAND" ] && grep -qF "$MARKER_LINE" "$COMMAND" 2>/dev/null; then
    rm -f "$COMMAND"
    removed="yes"
    say "Removed $COMMAND"
  fi
  if [ "$OS" = linux ]; then
    if [ -f "$APPLICATIONS/quillsail.desktop" ] && grep -q "X-QuillSail-Installer=true" "$APPLICATIONS/quillsail.desktop"; then
      rm -f "$APPLICATIONS/quillsail.desktop" "$ICONS/quillsail.svg"
      say "Removed the QuillSail menu entry"
    fi
  fi
  if [ -z "$removed" ]; then say "QuillSail wasn't installed by this installer, so nothing was removed."; fi
  say ""
  say "Your publications are still in $DATA_DIR. Delete that folder if you no longer need them."
  say "If your shell profile has a line marked \"Added by the QuillSail installer\", you can remove it too."
}

main() {
  parse_args "$@"
  detect_platform
  if [ "$UNINSTALL" = 1 ]; then
    uninstall
    return 0
  fi
  choose_folders
  check_requirements
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/quillsail-install.XXXXXX")"
  trap cleanup EXIT
  trap 'exit 130' INT TERM
  read_release
  current="$(installed_version)"
  if [ "$current" = "$VERSION" ]; then
    say "QuillSail $VERSION is already installed at $APP."
  else
    check_running
    download_and_check
    install_app
  fi
  write_command
  if [ "$OS" = linux ]; then write_desktop_entry; fi
  ensure_path
  summarize
}

main "$@"
