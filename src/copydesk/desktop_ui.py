"""Native launcher. Qt is optional for server and command-line installations."""

from __future__ import annotations

import argparse
import faulthandler
import json
import logging
import re
import sys
import tempfile
import threading
from pathlib import Path

from copydesk import __version__
from copydesk.desktop import (
    LOG_NAME,
    DesktopRuntime,
    default_data_dir,
    open_log,
    smoke_test,
    write_private,
)

log = logging.getLogger("copydesk.desktop")

# Ink on paper, with the logo's purple as the only accent. The launcher is light
# unless someone chooses dark, or automatic to follow the system appearance.
APPEARANCES = {"light": "Light", "dark": "Dark", "auto": "Automatic"}
PURPLE = "#6e4cc2"
TYPEFACES = {
    # Amiri Bold ships in static/fonts under the SIL Open Font License.
    "display": ("Amiri", "Big Caslon", "Georgia"),
    "text": ("Iowan Old Style", "Charter", "Sitka Text", "Palatino Linotype", "Georgia"),
    "label": ("Avenir Next", "Helvetica Neue", "Segoe UI", "Helvetica", "Arial"),
}
# Applied to the whole application so dialogs match the launcher window. Fonts
# are set here too: macOS resets per-class application fonts after startup.
STYLE = """
    QMainWindow, QDialog, QWidget#launcher-content, QScrollArea#launcher-scroll { background: @paper; border: 0; }
    QLabel, QComboBox, QLineEdit, QAbstractItemView { font-family: "@text"; font-size: 14px; }
    QLabel { color: @ink; background: transparent; }
    QLabel#masthead { font-family: "@display"; font-size: 42px; font-weight: 700; }
    QLabel#status { font-family: "@display"; font-size: 26px; font-weight: 700; }
    QLabel#tagline { font-size: 15px; font-style: italic; }
    QLabel[role="note"] { font-size: 13px; font-style: italic; }
    QLabel[role="kicker"] { font-family: "@label"; font-size: 11px; font-weight: 600; }
    QLabel#version { font-size: 10px; }
    QFrame#rule { background: @line; border: 0; }
    QPushButton { font-family: "@label"; font-size: 13px; font-weight: 500;
                  background: @paper; color: @ink; border: 1px solid @line; border-radius: 0; padding: 9px 14px; }
    QPushButton:hover, QPushButton:pressed { background: @wash; color: @inverse; }
    QPushButton:checked { background: @ink; border-color: @ink; color: @paper; }
    QPushButton:focus { border: 2px solid @purple; padding: 8px 13px; }
    QPushButton#primary { background: @purple; border-color: @purple; color: #ffffff; }
    QPushButton#primary:hover, QPushButton#primary:pressed { background: @wash; color: @inverse; }
    QPushButton#primary:focus { border-color: @ink; }
    QPushButton:disabled, QPushButton#primary:disabled { background: @paper; color: @faint; border: 1px solid @faint; }
    QPushButton[role="segment"] { padding: 7px 14px; }
    QPushButton[role="segment"]:focus { padding: 6px 13px; }
    QComboBox, QLineEdit { background: @paper; color: @ink; border: 1px solid @line; border-radius: 0; padding: 7px 9px;
                           selection-background-color: @purple; selection-color: #ffffff; }
    QComboBox:focus, QLineEdit:focus { border: 2px solid @purple; padding: 6px 8px; }
    QComboBox:disabled, QLineEdit:disabled { color: @faint; border-color: @faint; }
    QComboBox::drop-down { border: 0; width: 30px; }
    QComboBox::down-arrow { image: url("@chevron"); width: 12px; height: 8px; }
    QComboBox QAbstractItemView { background: @paper; color: @ink; border: 1px solid @line; outline: 0;
                                  selection-background-color: @purple; selection-color: #ffffff; }
    QProgressBar { background: @paper; border: 1px solid @line; border-radius: 0; max-height: 6px; }
    QProgressBar::chunk { background: @purple; }
"""


def saved_appearance(folder: Path) -> str:
    try:
        appearance = json.loads((folder / "launcher.json").read_text(encoding="utf-8")).get("appearance")
        if appearance in APPEARANCES:
            return appearance
    except (OSError, ValueError, AttributeError):
        pass
    return "light"


def save_appearance(folder: Path, appearance: str) -> None:
    if appearance not in APPEARANCES:
        raise ValueError("Choose a light, dark or automatic appearance.")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_private(folder / "launcher.json", json.dumps({"appearance": appearance}))


def run(*, data_dir: Path | None = None, instance_id: str | None = None, open_browser=True, smoke=False):
    try:
        from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, QUrl, Signal, Slot
        from PySide6.QtGui import (
            QAction,
            QColor,
            QDesktopServices,
            QFont,
            QFontDatabase,
            QFontMetrics,
            QIcon,
            QKeySequence,
            QPainter,
            QPalette,
        )
        from PySide6.QtNetwork import QLocalServer
        from PySide6.QtWidgets import (
            QApplication,
            QButtonGroup,
            QCheckBox,
            QComboBox,
            QFileDialog,
            QFrame,
            QHBoxLayout,
            QInputDialog,
            QLabel,
            QMainWindow,
            QMenu,
            QMessageBox,
            QProgressBar,
            QPushButton,
            QScrollArea,
            QSystemTrayIcon,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as exc:
        raise RuntimeError("Install the desktop extra with: pip install 'copydesk[desktop]'") from exc

    from copydesk.instances import InstanceRegistry, running_url
    from copydesk.launcher import COMMANDS, control_address, send_command
    from copydesk.update_install import InstallError, application_lock, read_install
    from copydesk.updater import (
        UpdateClient,
        install_lock_path,
        installation_path,
        last_install_result,
        launch_installer,
        save_channel,
        saved_channel,
    )

    default_root = default_data_dir().expanduser().resolve()
    root = (data_dir or default_root).expanduser().resolve()
    registry = InstanceRegistry()
    registered = next((item for item in registry.list() if item.root == root), None) if data_dir else None
    if data_dir and root != default_root and registered is None:
        registry = InstanceRegistry(root.with_name(root.name + "-instances"), default_root=root)
    rows = registry.list()
    selected = registry.get(instance_id) if instance_id else registered or next(iter(rows), None)
    # A second launch brings the open launcher forward instead of starting another.
    if send_command(registry.root, "show") == "ok":
        return 0
    appearance = saved_appearance(registry.root)
    root = selected.root if selected else registry.root
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    # The launcher outlives individual publications, including deleted ones.
    registry.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    logfile = registry.root / LOG_NAME
    handler = open_log(logfile)

    class Task(QObject):
        finished = Signal(object)
        failed = Signal(str)
        progress = Signal(str, int)

        def __init__(self, operation, parent):
            super().__init__(parent)
            self.operation = operation

        @Slot()
        def execute(self):
            try:
                self.finished.emit(self.operation())
            except Exception as exc:  # noqa: BLE001 - report errors inside the GUI
                log.exception("Desktop operation failed")
                self.failed.emit(str(exc))

    def apply_theme(appearance):
        dark = appearance == "dark" or (appearance == "auto" and app.styleHints().colorScheme() == Qt.ColorScheme.Dark)
        paper = QColor("#000000" if dark else "#ffffff")

        def ink(alpha):
            color = QColor("#ffffff" if dark else "#000000")
            color.setAlphaF(alpha)
            return color

        # Full-strength white on black glares, so the dark theme softens it.
        colors = {"paper": paper, "ink": ink(.86 if dark else 1), "line": ink(.4 if dark else 1),
                  "wash": ink(.14 if dark else 1), "faint": ink(.3 if dark else .4)}
        colors["inverse"] = colors["ink"] if dark else paper
        palette = QPalette()
        role = QPalette.ColorRole
        for name in (role.Window, role.Base, role.AlternateBase, role.Button, role.ToolTipBase):
            palette.setColor(name, paper)
        for name in (role.WindowText, role.Text, role.ButtonText, role.BrightText, role.ToolTipText, role.Link):
            palette.setColor(name, colors["ink"])
        for name in (role.WindowText, role.Text, role.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, name, colors["faint"])
        palette.setColor(role.PlaceholderText, colors["faint"])
        palette.setColor(role.Highlight, QColor(PURPLE))
        palette.setColor(role.HighlightedText, QColor("#ffffff"))
        app.setPalette(palette)
        tokens = {name: f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})" for name, c in colors.items()}
        tokens["purple"] = PURPLE
        tokens["chevron"] = (Path(__file__).parent / f"static/desktop/chevron-{'white' if dark else 'black'}.svg").as_posix()
        installed = set(QFontDatabase.families())
        for name, families in TYPEFACES.items():
            # Fall back to the last choice; Qt then substitutes a platform default.
            tokens[name] = next((family for family in families if family in installed), families[-1])
        app.setStyleSheet(re.sub(r"@(\w+)", lambda match: tokens[match.group(1)], STYLE))

    def kicker(text):
        label = QLabel(text)
        label.setProperty("role", "kicker")
        # The stylesheet sets the typeface; it cannot set capitals or tracking.
        font = label.font()
        font.setCapitalization(QFont.Capitalization.AllUppercase)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        label.setFont(font)
        return label

    def trim_line_box(label):
        # Amiri's line box leaves room for Arabic marks above and below.
        # Trim the space that Latin text leaves empty.
        label.ensurePolished()
        metrics = QFontMetrics(label.font())
        ink = metrics.tightBoundingRect("ÀÉQjgpy")
        top = max(0, metrics.ascent() + ink.top() - 2)
        bottom = max(0, metrics.descent() - ink.bottom() - 2)
        label.setContentsMargins(0, -top, 0, -bottom)

    def rule(weight=1):
        line = QFrame()
        line.setObjectName("rule")
        line.setFixedHeight(weight)
        return line

    class Logo(QLabel):
        def __init__(self, path):
            super().__init__()
            self.icon = QIcon(str(path))
            self.setFixedSize(QSize(52, 44))
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setAccessibleName("QuillSail logo")
            self.refresh()

        def refresh(self):
            # Request physical pixels for the current screen from the SVG engine.
            pixmap = self.icon.pixmap(QSize(52, 44), self.devicePixelRatioF())
            palette = app.palette()
            if palette.color(QPalette.ColorRole.Window).lightness() < 128:
                # The brand mark takes the ink color on dark surfaces.
                painter = QPainter(pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(), palette.color(QPalette.ColorRole.WindowText))
                painter.end()
            self.setPixmap(pixmap)

        def event(self, event):
            result = super().event(event)
            if event.type() in {QEvent.Type.Show, QEvent.Type.DevicePixelRatioChange} and hasattr(self, "icon"):
                self.refresh()
            return result

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.appearance = appearance
            self.runtime = self.make_runtime(root) if selected else None
            self.runtimes = {selected.id: self.runtime} if selected else {}
            self.selected_instance = selected
            self.external_url = ""
            self.busy = self.quitting = self.ready_to_quit = False
            # Like a menu bar app, closing the window leaves publications running.
            # Without a Dock or tray icon to reopen it, closing quits instead.
            self.keep_running_on_close = sys.platform == "darwin" or QSystemTrayIcon.isSystemTrayAvailable()
            self.task = self.thread = None
            self.smoke_starts, self.smoke_error = 0, False
            self.available_update = self.update_plan = None
            self.setWindowTitle("QuillSail")
            self.setMinimumSize(460, 600)
            icon_path = Path(__file__).parent / "static/brand/quillsail.svg"
            self.setWindowIcon(QIcon(str(icon_path)))
            content = QWidget()
            content.setObjectName("launcher-content")
            layout = QVBoxLayout(content)
            layout.setContentsMargins(36, 20, 36, 18)
            layout.setSpacing(8)
            brand = QHBoxLayout()
            brand.setSpacing(14)
            self.logo = Logo(icon_path)
            self.logo_ready = not self.logo.pixmap().isNull()
            if not self.logo_ready:
                log.error("The packaged QuillSail vector logo could not be rendered.")
            brand.addWidget(self.logo)
            # "Quill" stays logo purple; "Sail" takes the ink color.
            title = QLabel(f'<span style="color: {PURPLE}">Quill</span>Sail')
            title.setTextFormat(Qt.TextFormat.RichText)
            title.setAccessibleName("QuillSail")
            title.setObjectName("masthead")
            trim_line_box(title)
            brand.addWidget(title, 1)
            layout.addLayout(brand)
            layout.addWidget(rule(2))
            tagline = QLabel("Your publication, on your computer.")
            tagline.setObjectName("tagline")
            tagline.setWordWrap(True)
            layout.addWidget(tagline)
            layout.addWidget(rule())
            layout.addSpacing(4)
            instance_label = kicker("Publication instance")
            self.instance_selector = QComboBox()
            self.instance_selector.setObjectName("instance-selector")
            self.instance_selector.setAccessibleName("Publication instance")
            self.instance_selector.setPlaceholderText("No instances")
            instance_label.setBuddy(self.instance_selector)
            layout.addWidget(instance_label)
            # The selected instance and the action on it share a row.
            selector_row = QHBoxLayout()
            selector_row.setSpacing(8)
            selector_row.addWidget(self.instance_selector, 1)
            self.delete_instance_button = QPushButton("Delete instance…")
            self.delete_instance_button.clicked.connect(self.delete_instance)
            selector_row.addWidget(self.delete_instance_button)
            layout.addLayout(selector_row)
            instance_row = QHBoxLayout()
            instance_row.setSpacing(8)
            self.new_instance = QPushButton("New instance…")
            self.new_instance.clicked.connect(self.create_instance)
            instance_row.addWidget(self.new_instance)
            self.add_instance = QPushButton("Add existing…")
            self.add_instance.clicked.connect(self.add_existing_instance)
            instance_row.addWidget(self.add_instance)
            self.refresh_button = QPushButton("Refresh")
            self.refresh_button.clicked.connect(lambda: self.refresh_instances(self.selected_instance.id if self.selected_instance else None))
            instance_row.addWidget(self.refresh_button)
            layout.addLayout(instance_row)
            self.refresh_instances(selected.id if selected else None)
            self.instance_selector.currentIndexChanged.connect(self.select_instance)
            self.instance_summary = QLabel("No instances running in this launcher.")
            self.instance_summary.setProperty("role", "note")
            self.instance_summary.setWordWrap(True)
            layout.addWidget(self.instance_summary)
            layout.addSpacing(4)
            layout.addWidget(rule())
            layout.addWidget(kicker("Status"))
            self.status = QLabel("Starting your publication…")
            self.status.setObjectName("status")
            self.status.setWordWrap(True)
            trim_line_box(self.status)
            layout.addWidget(self.status)
            self.address = QLabel("The dashboard will open in your browser.")
            self.address.setWordWrap(True)
            layout.addWidget(self.address)
            self.public_status = QLabel("")
            self.public_status.setWordWrap(True)
            self.public_status.hide()
            layout.addWidget(self.public_status)
            self.public_button = QPushButton("Open public site")
            self.public_button.setMinimumHeight(44)
            self.public_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.runtime.public_url)) if self.runtime and self.runtime.public_url else None)
            self.public_button.hide()
            self.public_timer = QTimer(self)
            self.public_timer.timeout.connect(self.refresh_public_status)
            self.public_timer.start(2000)
            self.open_button = QPushButton("Open dashboard")
            self.open_button.setDefault(True)
            self.open_button.setMinimumHeight(44)
            self.open_button.setObjectName("primary")
            self.open_button.clicked.connect(self.open_dashboard)
            open_row = QHBoxLayout()
            open_row.setSpacing(8)
            open_row.addWidget(self.open_button, 1)
            open_row.addWidget(self.public_button)
            layout.addLayout(open_row)
            row = QHBoxLayout()
            row.setSpacing(8)
            self.toggle = QPushButton("Start")
            self.toggle.clicked.connect(lambda: self.stop() if self.runtime and self.runtime.server else self.start())
            row.addWidget(self.toggle)
            logs = QPushButton("View logs")
            logs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(logfile))))
            row.addWidget(logs)
            self.files_button = QPushButton("Open data folder")
            self.files_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.selected_instance.root))) if self.selected_instance else None)
            row.addWidget(self.files_button)
            layout.addLayout(row)
            layout.addSpacing(4)
            layout.addWidget(rule())
            layout.addWidget(kicker("Updates"))
            self.update_button = QPushButton("Check for updates")
            self.update_button.setAccessibleName("Check for QuillSail updates")
            self.update_button.clicked.connect(self.check_or_install_update)
            self.update_channel = QComboBox()
            self.update_channel.addItem("Stable", "stable")
            self.update_channel.addItem("Beta", "beta")
            self.update_channel.setCurrentIndex(0 if saved_channel() == "stable" else 1)
            channel_label = QLabel("Update channel")
            channel_label.setBuddy(self.update_channel)
            update_row = QHBoxLayout()
            update_row.setSpacing(8)
            update_row.addWidget(channel_label)
            update_row.addWidget(self.update_channel)
            update_row.addWidget(self.update_button, 1)
            layout.addLayout(update_row)
            self.update_channel.currentIndexChanged.connect(self.update_channel_changed)
            self.update_status = QLabel("Updates are installed only when you choose to install them.")
            self.update_status.setTextFormat(Qt.TextFormat.PlainText)
            self.update_status.setWordWrap(True)
            layout.addWidget(self.update_status)
            self.update_progress = QProgressBar()
            self.update_progress.setAccessibleName("Update progress")
            self.update_progress.setTextVisible(False)
            self.update_progress.hide()
            layout.addWidget(self.update_progress)
            layout.addSpacing(4)
            layout.addWidget(rule())
            self.appearance_buttons = {}
            choices = QButtonGroup(self)
            appearance_row = QHBoxLayout()
            appearance_row.setSpacing(8)
            appearance_row.addWidget(kicker("Appearance"))
            appearance_row.addStretch()
            for value, name in APPEARANCES.items():
                choice = QPushButton(name)
                choice.setProperty("role", "segment")
                choice.setCheckable(True)
                choice.setChecked(value == appearance)
                choice.setAccessibleName(name + " appearance")
                choice.clicked.connect(lambda _checked, value=value: self.choose_appearance(value))
                choices.addButton(choice)
                appearance_row.addWidget(choice)
                self.appearance_buttons[value] = choice
            layout.addLayout(appearance_row)
            layout.addStretch()
            layout.addWidget(rule())
            footer = QHBoxLayout()
            footer.setSpacing(16)
            notes = QVBoxLayout()
            notes.setSpacing(4)
            note = QLabel("Closing this window keeps your publications running. Quit QuillSail to stop them; their content stays saved."
                          if self.keep_running_on_close else
                          "Instances can run together. Closing QuillSail stops all instances started here; their content stays saved.")
            note.setProperty("role", "note")
            note.setWordWrap(True)
            notes.addWidget(note)
            version = kicker(f"Version {__version__} · Local access only")
            version.setObjectName("version")
            notes.addWidget(version)
            footer.addLayout(notes, 1)
            self.quit_button = QPushButton("Quit QuillSail")
            self.quit_button.clicked.connect(self.request_quit)
            footer.addWidget(self.quit_button)
            layout.addLayout(footer)
            scroll = QScrollArea()
            scroll.setObjectName("launcher-scroll")
            scroll.setWidgetResizable(True)
            scroll.setWidget(content)
            self.setCentralWidget(scroll)
            # Text that wraps onto more lines, a public address or update progress
            # can make the content taller after the window opens.
            content.installEventFilter(self)
            app.styleHints().colorSchemeChanged.connect(self.appearance_changed)
            close_action = QAction("Close Window", self)
            close_action.setShortcut(QKeySequence.StandardKey.Close)
            close_action.triggered.connect(self.close)
            quit_action = QAction("Quit QuillSail", self)
            quit_action.setShortcut("Ctrl+Q")
            quit_action.setMenuRole(QAction.MenuRole.QuitRole)
            quit_action.triggered.connect(self.request_quit)
            menu = self.menuBar().addMenu("QuillSail")
            menu.addAction(close_action)
            menu.addAction(quit_action)
            self.tray = None
            if QSystemTrayIcon.isSystemTrayAvailable():
                tray_icon = QIcon(str(icon_path))
                tray_icon.setIsMask(True)  # macOS draws it to match the menu bar.
                self.tray = QSystemTrayIcon(tray_icon, self)
                self.tray.setToolTip("QuillSail")
                tray_menu = QMenu(self)
                tray_menu.addAction("Open QuillSail", self.show_window)
                tray_menu.addSeparator()
                tray_menu.addAction(quit_action)
                self.tray.setContextMenu(tray_menu)
                self.tray.activated.connect(self.tray_activated)
                self.tray.show()
            # macOS sends a forced activation when someone clicks the Dock icon.
            app.applicationStateChanged.connect(self.application_state_changed)
            self.listen_for_commands()
            self.select_instance()
            content.ensurePolished()
            self.resize(540, self.minimumHeight())
            self.fit_content()
            QTimer.singleShot(0, self.start)

        def fit_content(self):
            """Grow the window so everything shows without scrolling, as far as the screen allows."""
            if self.isMaximized() or self.isFullScreen():
                return
            menu = 0 if self.menuBar().isNativeMenuBar() else self.menuBar().sizeHint().height()
            needed = self.centralWidget().widget().heightForWidth(self.width()) + menu
            # The title bar is outside the window's height. Until it exists, allow for a tall one.
            frame = self.frameGeometry().height() - self.height() if self.isVisible() else 40
            screen = self.screen().availableGeometry()
            if (height := min(needed, screen.height() - frame)) > self.height():
                self.resize(self.width(), height)
                if self.isVisible() and self.frameGeometry().bottom() > screen.bottom():
                    self.move(self.x(), max(screen.top(), screen.bottom() + 1 - self.frameGeometry().height()))

        def showEvent(self, event):  # noqa: N802 - Qt virtual method
            super().showEvent(event)
            # The real title bar height is known once the window is shown.
            QTimer.singleShot(0, self.fit_content)

        def eventFilter(self, _watched, event):  # noqa: N802 - Qt virtual method
            if event.type() == QEvent.Type.LayoutRequest:
                QTimer.singleShot(0, self.fit_content)
            return False

        def listen_for_commands(self):
            """Accept show and quit requests from `quillsail quit` or a second launch."""
            self.control = QLocalServer(self)
            self.control.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
            address = control_address(registry.root)
            if not self.control.listen(address):
                # Nothing answered before this launcher opened, so the socket is stale.
                QLocalServer.removeServer(address)
                if not self.control.listen(address):
                    log.error("QuillSail cannot accept quit requests from the command line: %s", self.control.errorString())
            self.control.newConnection.connect(self.accept_commands)

        def accept_commands(self):
            while (connection := self.control.nextPendingConnection()) is not None:
                connection.readyRead.connect(lambda connection=connection: self.read_command(connection))
                connection.disconnected.connect(connection.deleteLater)

        def read_command(self, connection):
            if not connection.canReadLine():
                return
            command = bytes(connection.readLine()).decode(errors="replace").strip()
            connection.write(b"ok\n" if command in COMMANDS else b"unknown\n")
            connection.flush()
            connection.disconnectFromServer()
            if command == "show":
                self.show_window()
            elif command == "quit":
                self.request_quit()

        def show_window(self):
            self.showNormal()
            self.raise_()
            self.activateWindow()

        def tray_activated(self, reason):
            # The tray menu opens on its own; a plain click opens the window.
            if reason == QSystemTrayIcon.ActivationReason.Trigger and sys.platform != "darwin":
                self.show_window()

        def application_state_changed(self, state):
            if state == Qt.ApplicationState.ApplicationActive and self.isHidden() and not self.quitting:
                self.show_window()

        def request_quit(self):
            """Stop every publication this launcher started, then exit."""
            self.quitting = True
            self.quit_button.setEnabled(False)
            if self.busy:
                return  # The running operation checks self.quitting when it finishes.
            if any(runtime.server for runtime in self.runtimes.values()):
                self.stop()
            else:
                self.ready_to_quit = True
                if self.tray:
                    self.tray.hide()
                app.quit()

        def appearance_changed(self, _scheme=None):
            apply_theme(self.appearance)
            self.logo.refresh()

        def make_runtime(self, directory):
            runtime = DesktopRuntime(directory)
            # The browser setup page follows the launcher's appearance.
            runtime.appearance = self.appearance
            return runtime

        def choose_appearance(self, value):
            self.appearance = value
            for runtime in self.runtimes.values():
                runtime.appearance = value
            self.appearance_changed()
            try:
                save_appearance(registry.root, value)
            except OSError:
                log.exception("The launcher appearance could not be saved for the next launch.")

        def refresh_instances(self, selected_id=None):
            self.instance_selector.blockSignals(True)
            self.instance_selector.clear()
            for item in registry.list():
                self.instance_selector.addItem(item.name, item.id)
            index = self.instance_selector.findData(selected_id)
            self.instance_selector.setCurrentIndex(max(0, index) if self.instance_selector.count() else -1)
            self.instance_selector.blockSignals(False)
            if hasattr(self, "status"):
                self.select_instance()

        def refresh_public_status(self):
            address = getattr(self.runtime, "public_url", "")
            tunnel = getattr(self.runtime, "tunnel", None)
            status = tunnel.status if tunnel else "Offline"
            if getattr(self.runtime, "hosting_status", ""):
                status = self.runtime.hosting_status
            self.public_status.setText(f"Public address: {address} · {status}" if address else "")
            self.public_status.setVisible(bool(address))
            self.public_button.setVisible(bool(address))

        def refresh_running_labels(self):
            count = sum(bool(runtime.server) for runtime in self.runtimes.values())
            self.instance_summary.setText(f"{count} instance{'s' if count != 1 else ''} running in this launcher.")
            for index in range(self.instance_selector.count()):
                identifier = self.instance_selector.itemData(index)
                item = registry.get(identifier)
                runtime = self.runtimes.get(identifier)
                self.instance_selector.setItemText(index, item.name + (" · Running" if runtime and runtime.server else ""))

        def select_instance(self):
            if self.instance_selector.currentData() is None:
                self.selected_instance = self.runtime = None
                self.external_url = ""
                self.setWindowTitle("QuillSail")
                self.status.setText("Create or add an instance")
                self.address.setText("Choose New instance… to create a publication, or Add existing… to open a saved publication folder.")
                self.toggle.setText("Start")
                self.restore_instance_controls()
                self.refresh_running_labels()
                return
            self.selected_instance = registry.get(self.instance_selector.currentData())
            identifier = self.selected_instance.id
            if identifier not in self.runtimes:
                self.runtimes[identifier] = self.make_runtime(self.selected_instance.root)
            self.runtime = self.runtimes[identifier]
            self.setWindowTitle(self.selected_instance.name + " · QuillSail")
            external = running_url(self.selected_instance) if not self.runtime.server else ""
            self.external_url = external
            self.status.setText("Running in another launcher or terminal." if external else
                                "Your publication is running" if self.runtime.server else "Stopped. Your content is saved.")
            self.address.setText(external or self.runtime.url if self.runtime.server or external else "Start this instance to open its dashboard.")
            self.toggle.setText("Stop" if self.runtime.server else "Start")
            self.restore_instance_controls()
            self.refresh_running_labels()
            self.refresh_public_status()

        def restore_instance_controls(self):
            selected = self.selected_instance is not None
            running = bool(self.runtime and self.runtime.server)
            self.instance_selector.setEnabled(bool(self.instance_selector.count()) and not self.busy)
            self.toggle.setEnabled(selected and not self.external_url and not self.busy)
            self.open_button.setEnabled(bool(running or self.external_url) and not self.busy)
            self.files_button.setEnabled(selected and not self.busy)
            self.delete_instance_button.setEnabled(selected and not self.external_url and not self.busy)
            self.delete_instance_button.setToolTip("Stop this instance in its other launcher or terminal before deleting it." if self.external_url else "")

        def delete_instance(self):
            if self.busy or self.quitting or self.selected_instance is None:
                return
            item = self.selected_instance
            dialog = QMessageBox(self)
            dialog.setWindowTitle("Delete instance")
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(f"Remove {item.name} from the instance list?")
            dialog.setInformativeText(f"QuillSail will finish background work and stop this instance before removing it. Files will be kept in {item.root} unless you choose to permanently delete them, including content and subscribers.")
            erase = QCheckBox("Permanently delete publication files")
            dialog.setCheckBox(erase)
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            dialog.button(QMessageBox.StandardButton.Ok).setText("Stop and delete" if self.runtime.server else "Delete instance")
            dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if dialog.exec() == QMessageBox.StandardButton.Ok:
                delete_data = erase.isChecked()
                runtime = self.runtime
                self.status.setText("Finishing background work and deleting the instance…")
                self.operation(lambda: registry.delete(item.id, delete_data=delete_data, runtime=runtime), self.instance_deleted, self.delete_failed)

        @Slot(str)
        def delete_failed(self, message):
            self.finish_operation()
            self.busy = False
            self.select_instance()
            self.status.setText("The instance could not be deleted: " + message)
            if self.quitting:
                QTimer.singleShot(0, self.request_quit)

        @Slot(object)
        def instance_deleted(self, item):
            self.finish_operation()
            self.busy = False
            self.runtimes.pop(item.id, None)
            self.refresh_instances()
            if self.quitting:
                QTimer.singleShot(0, self.request_quit)

        def create_instance(self):
            name, accepted = QInputDialog.getText(self, "New publication instance", "Instance name")
            if accepted and name.strip():
                self.status.setText("Creating a separate publication…")
                self.operation(lambda: registry.add(name), self.instance_added)

        def add_existing_instance(self):
            directory = QFileDialog.getExistingDirectory(self, "Choose a QuillSail publication data folder")
            if not directory:
                return
            name, accepted = QInputDialog.getText(self, "Add existing instance", "Instance name")
            if accepted and name.strip():
                self.operation(lambda: registry.add(name, Path(directory), existing=True), self.instance_added)

        @Slot(object)
        def instance_added(self, item):
            self.finish_operation()
            self.busy = False
            self.refresh_instances(item.id)
            if self.quitting:
                QTimer.singleShot(0, self.request_quit)
            elif not self.external_url:
                self.start()

        def operation(self, callback, completed, on_failed=None):
            self.busy = True
            self.toggle.setEnabled(False)
            self.open_button.setEnabled(False)
            self.update_button.setEnabled(False)
            self.update_channel.setEnabled(False)
            self.instance_selector.setEnabled(False)
            self.new_instance.setEnabled(False)
            self.delete_instance_button.setEnabled(False)
            self.files_button.setEnabled(False)
            self.add_instance.setEnabled(False)
            self.refresh_button.setEnabled(False)
            self.task = Task(callback, self)
            self.task.finished.connect(completed, Qt.ConnectionType.QueuedConnection)
            self.task.failed.connect(on_failed or self.failed, Qt.ConnectionType.QueuedConnection)
            self.task.progress.connect(self.update_progress_changed, Qt.ConnectionType.QueuedConnection)
            self.thread = threading.Thread(target=self.task.execute, name="quillsail-desktop-action", daemon=True)
            self.thread.start()

        def finish_operation(self):
            # The queued result can arrive just before the worker returns.
            # Join it before replacing any task or deleting the window tree.
            self.thread.join()
            self.task.deleteLater()
            self.update_button.setEnabled(True)
            self.update_channel.setEnabled(True)
            self.new_instance.setEnabled(True)
            self.add_instance.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.busy = False
            self.restore_instance_controls()

        def update_channel_changed(self):
            self.available_update = None
            self.update_button.setText("Check for updates")
            self.update_status.setText("Check for an update on the selected channel.")
            try:
                save_channel(self.update_channel.currentData())
            except OSError:
                self.update_status.setText("This channel is selected, but the preference could not be saved for the next launch.")

        @Slot(str, int)
        def update_progress_changed(self, message, percent):
            self.update_status.setText(message)
            self.update_progress.show()
            self.update_progress.setRange(0, 0 if percent < 0 else 100)
            if percent >= 0:
                self.update_progress.setValue(percent)

        def check_or_install_update(self):
            if self.busy or self.quitting:
                return
            if self.available_update is None:
                self.update_progress_changed("Checking for updates…", -1)
                channel = self.update_channel.currentData()
                target = read_install(installation)["target"] if installation else None
                self.operation(lambda: UpdateClient().check(channel=channel, target=target), self.update_checked, self.update_failed)
                return
            release = self.available_update
            dialog = QMessageBox(self)
            dialog.setWindowTitle("Update QuillSail")
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(f"Download and install QuillSail {release.version}?")
            dialog.setInformativeText("QuillSail will finish background work for all instances started here, install the verified update, and restart. All publication files stay saved. Stop instances launched in other terminals or apps before updating.")
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            dialog.button(QMessageBox.StandardButton.Ok).setText("Download and restart")
            dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if dialog.exec() != QMessageBox.StandardButton.Ok:
                return
            try:
                install_root = installation_path()
            except Exception as exc:  # noqa: BLE001 - show a useful source-install message
                self.update_status.setText(str(exc))
                return
            self.update_progress_changed("Downloading update…", 0)
            data_dir = self.selected_instance.root if self.selected_instance else registry.root
            self.operation(lambda: UpdateClient().prepare(release, install_root, data_dir=data_dir,
                           progress=lambda message, percent: self.task.progress.emit(message, percent)),
                           self.update_prepared, self.update_failed)

        @Slot(object)
        def update_checked(self, update):
            self.finish_operation()
            self.busy = False
            self.restore_instance_controls()
            self.update_progress.hide()
            if self.quitting:
                QTimer.singleShot(0, self.request_quit)
                return
            self.available_update = update if update.available else None
            self.update_button.setText(f"Install QuillSail {update.version}…" if update.available else "Check for updates")
            self.update_status.setText(f"QuillSail {update.version} is available on the {update.channel} channel."
                                       if update.available else f"QuillSail {__version__} is up to date on the {update.channel} channel.")

        @Slot(object)
        def update_prepared(self, plan):
            self.finish_operation()
            self.busy = False
            self.update_plan = plan
            self.quitting = True
            self.update_progress_changed("Finishing background work before updating…", -1)
            self.stop()

        @Slot(str)
        def update_failed(self, message):
            handoff_failed = self.update_plan is not None
            self.finish_operation()
            self.busy = False
            self.available_update = self.update_plan = None
            self.update_button.setText("Check for updates")
            self.update_status.setText(message)
            self.update_progress.hide()
            self.restore_instance_controls()
            if self.quitting:
                if handoff_failed:
                    self.quitting = False
                    self.quit_button.setEnabled(True)
                    if self.runtime and self.runtime.server is None:
                        QTimer.singleShot(0, self.start)
                else:
                    QTimer.singleShot(0, self.request_quit)

        def start(self):
            if not self.busy and self.selected_instance is not None:
                if external := running_url(self.selected_instance):
                    self.external_url = external
                    self.select_instance()
                    return
                self.status.setText("Starting your publication…")
                self.operation(self.runtime.start, self.started)

        @Slot(object)
        def started(self, url):
            self.finish_operation()
            self.busy = False
            self.status.setText("Your publication is running")
            self.address.setText(url)
            self.toggle.setText("Stop")
            self.toggle.setEnabled(True)
            self.open_button.setEnabled(True)
            self.refresh_running_labels()
            if smoke:
                self.smoke_starts += 1
                QTimer.singleShot(0, self.stop if self.smoke_starts == 1 else self.request_quit)
            elif self.quitting:
                QTimer.singleShot(0, self.stop)
            elif open_browser:
                self.open_dashboard()

        def open_dashboard(self):
            if self.selected_instance is None:
                return
            url = self.runtime.launch_url() if self.runtime.server else running_url(self.selected_instance) + "/dashboard/"
            if not QDesktopServices.openUrl(QUrl(url)):
                self.status.setText("Your browser could not be opened. Try Open dashboard again.")

        def stop(self):
            if not self.busy:
                self.status.setText("Finishing background work and stopping…")
                def stop_and_handoff():
                    for runtime in self.runtimes.values() if self.quitting else ((self.runtime,) if self.runtime else ()):
                        runtime.stop()
                    if self.update_plan is not None:
                        launch_installer(self.update_plan)
                self.operation(stop_and_handoff, self.stopped, self.update_failed if self.update_plan else None)

        @Slot(object)
        def stopped(self, _result=None):
            self.finish_operation()
            self.busy = False
            self.status.setText("Stopped. Your content is saved.")
            self.address.setText("Start QuillSail to open your dashboard.")
            self.toggle.setText("Start")
            self.restore_instance_controls()
            self.refresh_running_labels()
            if self.quitting:
                QTimer.singleShot(0, self.request_quit)
            elif smoke:
                QTimer.singleShot(0, self.start)

        @Slot(str)
        def failed(self, message):
            self.finish_operation()
            self.busy = False
            self.status.setText("QuillSail could not start: " + message)
            self.address.setText("View logs for details. Your publication files are in the data folder.")
            self.toggle.setText("Start")
            self.restore_instance_controls()
            if smoke:
                self.smoke_error = True
            if smoke or self.quitting:
                QTimer.singleShot(0, self.request_quit)

        def closeEvent(self, event):  # noqa: N802 - Qt virtual method
            if self.ready_to_quit:
                event.accept()
                return
            event.ignore()
            if self.keep_running_on_close and not self.quitting:
                # Publications keep running until someone quits QuillSail.
                self.hide()
            else:
                self.request_quit()

    class QuitRequests(QObject):
        """The Dock's Quit command and logging out arrive as an application Quit event."""

        def eventFilter(self, _watched, event):  # noqa: N802 - Qt virtual method
            if event.type() == QEvent.Type.Quit and not window.ready_to_quit:
                window.request_quit()
                return True  # Quit only after the publications have stopped.
            return False

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("QuillSail")
    app.setOrganizationName("QuillSail")
    # Closing the window hides it; QuillSail exits only when someone quits.
    app.setQuitOnLastWindowClosed(False)
    if QFontDatabase.addApplicationFont(str(Path(__file__).parent / "static/fonts/Amiri-Bold.ttf")) < 0:
        log.error("The packaged display font could not be loaded; using a system serif.")
    apply_theme(appearance)
    guard = None
    installation = installation_path() if getattr(sys, "frozen", False) else None
    if installation:
        guard = application_lock(install_lock_path(installation))
        try:
            guard.__enter__()
        except InstallError as exc:
            QMessageBox.information(None, "QuillSail is already open", str(exc))
            handler.close()
            logging.getLogger().removeHandler(handler)
            return 1
    window = Window()
    quit_requests = QuitRequests()
    app.installEventFilter(quit_requests)
    if installation and (last := last_install_result(installation)) and last.get("status") == "failed":
        window.update_status.setText("The last update could not be installed. " + last.get("error", "Try checking for updates again."))
    window.show()
    try:
        result = app.exec()
        return 1 if smoke and (window.smoke_error or window.smoke_starts != 2 or not window.logo_ready) else result
    finally:
        app.removeEventFilter(quit_requests)
        window.control.close()
        if window.tray:
            window.tray.hide()
        if window.thread is not None:
            window.thread.join()
        for runtime in window.runtimes.values():
            runtime.stop()
        # Destroy the widget tree while QApplication still exists. Leaving it
        # to Python/Qt's atexit order can double-delete child wrappers in a bundle.
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        logging.getLogger().removeHandler(handler)
        handler.close()
        if guard:
            guard.__exit__(None, None, None)


def attach_windows_console():
    """The Windows app has no console of its own, so borrow the terminal that ran it.

    A stream that already exists was redirected to a file or pipe, so it stays as it is.
    """
    import ctypes

    if not ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
        return
    if sys.stdin is None:
        sys.stdin = open("CONIN$", encoding="utf-8", errors="replace")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115


def main():
    if getattr(sys, "frozen", False):
        from copydesk.installed_command import refresh_installed_command

        refresh_installed_command()
    # The installed `quillsail` command adds "cli". Opening the app from a menu or
    # the Finder passes nothing, which opens the window below.
    if sys.argv[1:2] == ["cli"]:
        if sys.platform == "win32":
            attach_windows_console()
        from copydesk.cli import main as cli_main

        cli_main(sys.argv[2:], prog_name="quillsail")
        return
    parser = argparse.ArgumentParser(description="Open QuillSail on your computer.")
    parser.add_argument("--data-dir", type=Path, help="Use a separate desktop publication folder.")
    parser.add_argument("--instance", help="Open a named local publication from the shared instance list.")
    parser.add_argument("--no-browser", action="store_true", help="Start the launcher without opening the browser.")
    parser.add_argument("--smoke-test", action="store_true", help="Check a disposable local publication, then exit.")
    parser.add_argument("--smoke-test-gui", action="store_true", help="Check native window startup, stop and restart with disposable data.")
    update = parser.add_mutually_exclusive_group()
    update.add_argument("--check-updates", action="store_true", help="Check for a signed desktop update, then exit.")
    update.add_argument("--update", action="store_true", help="Download and install an available signed desktop update.")
    parser.add_argument("--channel", choices=("stable", "beta"), default="beta", help="Desktop update channel.")
    parser.add_argument("--yes", action="store_true", help="Approve a command-line update without prompting.")
    parser.add_argument("--version", action="version", version="QuillSail " + __version__)
    args = parser.parse_args()
    if args.data_dir and args.instance:
        parser.error("Choose --data-dir or --instance, rather than both.")
    if args.check_updates or args.update:
        from copydesk.cli import main as cli_main

        command = ["update", "--desktop", "--channel", args.channel]
        if args.check_updates:
            command.append("--check")
        if args.yes:
            command.append("--yes")
        cli_main(command, prog_name="QuillSail")
        return
    if (args.smoke_test or args.smoke_test_gui) and sys.stderr is not None:
        faulthandler.enable()
    if args.smoke_test:
        smoke_test()
        return
    if args.smoke_test_gui:
        with tempfile.TemporaryDirectory(prefix="quillsail-gui-smoke-") as directory:
            raise SystemExit(run(data_dir=Path(directory), open_browser=False, smoke=True))
    raise SystemExit(run(data_dir=args.data_dir, instance_id=args.instance, open_browser=not args.no_browser))


if __name__ == "__main__":
    main()
