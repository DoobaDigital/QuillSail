"""Exercise native close handling without a server, browser or mailbox."""

import os
import subprocess
import sys
import textwrap

import pytest


def test_gui_closes_after_stopping_without_recursive_quit(tmp_path):
    pytest.importorskip("PySide6")
    script = textwrap.dedent("""
        import sys
        from pathlib import Path
        from copydesk import desktop_ui

        class Runtime:
            starts = stops = 0

            def __init__(self, root):
                self.server = None

            def start(self):
                type(self).starts += 1
                self.server = True
                return "http://127.0.0.1:5080"

            def stop(self):
                if self.server:
                    type(self).stops += 1
                self.server = None

        desktop_ui.DesktopRuntime = Runtime
        assert desktop_ui.run(data_dir=Path(sys.argv[1]), open_browser=False, smoke=True) == 0
        assert (Runtime.starts, Runtime.stops) == (2, 2)
    """)
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("scenario", ["available", "current", "offline", "install", "elsewhere"])
def test_update_controls_keep_publication_running_until_an_approved_install(tmp_path, scenario):
    pytest.importorskip("PySide6")
    script = textwrap.dedent("""
        import sys
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox
        from copydesk import __version__, desktop_ui, instances, updater

        scenario, root = sys.argv[1], Path(sys.argv[2])
        calls = []
        if scenario == 'elsewhere':
            registered = instances.InstanceRegistry.list
            other = instances.Instance('other', 'Other Site', root.parent / 'other')
            instances.InstanceRegistry.list = lambda self: [*registered(self), other]
            instances.running_url = lambda item: 'http://127.0.0.1:5999' if item.id == 'other' else ''

        class Runtime:
            def __init__(self, root):
                self.server = None
            def start(self):
                calls.append('start')
                self.server = True
                return 'http://127.0.0.1:5080'
            def stop(self):
                if self.server:
                    calls.append('stop')
                self.server = None

        class Client:
            def check(self, **kwargs):
                if scenario == 'offline':
                    raise updater.UpdateError('Synthetic offline update service')
                return updater.Update(__version__, __version__ if scenario == 'current' else '9.0.0',
                                      'linux-x86_64', 'beta', 'synthetic.zip', 123, 'a'*64)
            def prepare(self, update, installation, **kwargs):
                assert calls == ['start']
                calls.append('prepare')
                return root / 'synthetic-plan.json'

        def handoff(plan):
            assert calls == ['start', 'prepare', 'stop']
            calls.append('handoff')

        desktop_ui.DesktopRuntime = Runtime
        updater.UpdateClient = Client
        updater.saved_channel = lambda: 'beta'
        updater.save_channel = lambda channel: None
        updater.installation_path = lambda: root / 'synthetic.app'
        updater.launch_installer = handoff
        QMessageBox.exec = lambda self: QMessageBox.StandardButton.Ok
        app = QApplication([])
        state = [0]
        errors = []

        def inspect():
            try:
                windows = [w for w in app.topLevelWidgets() if isinstance(w, QMainWindow)]
                if not windows:
                    return
                window = windows[0]
                if state[0] == 0 and not window.busy and window.runtime.server:
                    window.resize(460, 500)
                    app.processEvents()
                    for label in window.findChildren(QLabel):
                        if label.wordWrap():
                            assert label.height() >= label.heightForWidth(label.width()), label.text()
                    state[0] = 1
                    window.update_button.click()
                elif state[0] == 1 and not window.busy:
                    assert calls == ['start']
                    assert window.open_button.isEnabled()
                    assert not window.update_progress.isVisible()
                    if scenario == 'offline':
                        assert 'Synthetic offline' in window.update_status.text()
                        window.request_quit()
                        state[0] = 3
                    elif scenario == 'current':
                        assert 'up to date' in window.update_status.text()
                        window.request_quit()
                        state[0] = 3
                    elif scenario == 'available':
                        assert '9.0.0' in window.update_button.text()
                        window.update_channel.setCurrentIndex(0)
                        assert window.available_update is None
                        assert window.update_button.text() == 'Check for updates'
                        window.request_quit()
                        state[0] = 3
                    elif scenario == 'elsewhere':
                        # Terminal instances run from the files that the update replaces.
                        window.update_button.click()
                        assert calls == ['start'] and not window.busy
                        assert 'Stop Other Site first' in window.update_status.text()
                        window.request_quit()
                        state[0] = 3
                    else:
                        state[0] = 2
                        window.update_button.click()
            except BaseException as exc:
                errors.append(repr(exc))
                app.exit(1)

        timer = QTimer()
        timer.timeout.connect(inspect)
        timer.start(10)
        QTimer.singleShot(10_000, lambda: (errors.append('GUI test timed out'), app.exit(1)))
        assert desktop_ui.run(data_dir=root, open_browser=False) == 0, errors
        assert not errors, errors
        assert calls == (['start', 'prepare', 'stop', 'handoff'] if scenario == 'install' else ['start', 'stop']), calls
    """)
    result = subprocess.run([sys.executable, "-c", script, scenario, str(tmp_path)],
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_launcher_shows_all_content_without_scrolling(tmp_path):
    pytest.importorskip("PySide6")
    script = textwrap.dedent("""
        import sys
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMainWindow, QScrollArea
        from copydesk import desktop_ui

        class Runtime:
            def __init__(self, root):
                self.server = None
                self.public_url = ''
            def start(self):
                self.server = True
                return 'http://127.0.0.1:5080'
            def stop(self):
                self.server = None

        desktop_ui.DesktopRuntime = Runtime
        app = QApplication([])
        state, heights, errors = [0], [], []

        def check_fit(window):
            # Everything shows, unless the window already fills the screen.
            screen = window.screen().availableGeometry()
            frame = window.frameGeometry()
            scroll = window.findChild(QScrollArea, 'launcher-scroll')
            assert screen.contains(frame), (screen, frame)
            assert scroll.verticalScrollBar().maximum() == 0 or frame.height() >= screen.height() - 1, \\
                (window.height(), scroll.widget().heightForWidth(window.width()))
            heights.append(window.height())

        def inspect():
            try:
                window = next((w for w in app.topLevelWidgets() if isinstance(w, QMainWindow) and w.isVisible()), None)
                if window is None or window.busy or not window.runtime.server:
                    return
                if state[0] == 0:
                    check_fit(window)
                    # A public address adds a line, so the window grows instead of scrolling.
                    window.runtime.public_url = 'https://news.example.org'
                    window.refresh_public_status()
                elif state[0] == 10:
                    assert window.public_status.isVisible() and window.public_button.isVisible()
                    check_fit(window)
                    full = window.frameGeometry().height() >= window.screen().availableGeometry().height() - 1
                    assert heights[1] > heights[0] or full, heights
                    window.request_quit()
                state[0] += 1
            except BaseException as exc:
                errors.append(repr(exc))
                app.exit(1)

        timer = QTimer()
        timer.timeout.connect(inspect)
        timer.start(10)
        QTimer.singleShot(10_000, lambda: (errors.append('GUI test timed out'), app.exit(1)))
        assert desktop_ui.run(data_dir=Path(sys.argv[1]), open_browser=False) == 0, errors
        assert not errors, errors
    """)
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('action', ['close', 'update'])
def test_instance_switching_keeps_other_publications_running_and_shutdown_stops_all(tmp_path, action):
    pytest.importorskip('PySide6')
    script = textwrap.dedent('''
        import sys
        from pathlib import Path
        import requests
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QInputDialog, QMainWindow, QMessageBox
        from copydesk import __version__, desktop_ui, updater

        root, action = Path(sys.argv[1]), sys.argv[2]
        app = QApplication([])
        errors, owned, handoffs = [], [], []
        phase = [0]
        QInputDialog.getText = lambda *a, **k: ('Second publication', True)
        QMessageBox.exec = lambda self: QMessageBox.StandardButton.Ok
        updater.saved_channel = lambda: 'beta'
        updater.save_channel = lambda value: None
        updater.installation_path = lambda: root / 'synthetic.app'
        class Client:
            def check(self, **kwargs):
                return updater.Update(__version__, '9.0.0', 'linux-x86_64', 'beta', 'synthetic.zip', 123, 'a'*64)
            def prepare(self, *args, **kwargs):
                assert all(runtime.server for runtime in owned)
                return root / 'plan.json'
        updater.UpdateClient = Client
        def handoff(plan):
            assert all(runtime.server is None for runtime in owned)
            handoffs.append(plan)
        updater.launch_installer = handoff

        def inspect():
            try:
                windows = [w for w in app.topLevelWidgets() if isinstance(w, QMainWindow)]
                if not windows:
                    return
                window = windows[0]
                if window.busy:
                    return
                if phase[0] == 0 and window.runtime.server:
                    owned.append(window.runtime)
                    phase[0] = 1
                    window.new_instance.click()
                elif phase[0] == 1 and window.runtime.server and len(window.runtimes) == 2:
                    owned.append(window.runtime)
                    assert owned[0] is not owned[1]
                    assert owned[0].url != owned[1].url
                    window.instance_selector.setCurrentIndex(window.instance_selector.findData('default'))
                    assert window.runtime is owned[0]
                    assert all(runtime.server for runtime in owned)
                    phase[0] = 2
                    if action == 'close':
                        window.toggle.click()
                    else:
                        window.update_button.click()
                elif phase[0] == 2:
                    if action == 'close':
                        assert owned[0].server is None
                        assert requests.get(owned[1].url + '/healthz', timeout=5).status_code == 200
                        phase[0] = 3
                        window.request_quit()
                    elif window.available_update:
                        phase[0] = 3
                        window.update_button.click()
            except BaseException as exc:
                errors.append(repr(exc))
                app.exit(1)
        timer = QTimer()
        timer.timeout.connect(inspect)
        timer.start(20)
        QTimer.singleShot(20_000, lambda: (errors.append('Multiple-instance GUI test timed out'), app.exit(1)))
        assert desktop_ui.run(data_dir=root, open_browser=False) == 0, errors
        assert not errors and phase[0] == 3, errors
        assert len(owned) == 2 and all(runtime.server is None for runtime in owned)
        assert len(handoffs) == (1 if action == 'update' else 0)
    ''')
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'default'), action],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, capture_output=True,
                            text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr


def test_launcher_defaults_to_light_and_dialogs_stay_readable_in_each_appearance(tmp_path):
    pytest.importorskip("PySide6")
    script = textwrap.dedent("""
        import sys
        from pathlib import Path
        from PySide6.QtCore import QPoint, QTimer
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QMainWindow, QMessageBox
        from copydesk import desktop_ui

        class Runtime:
            def __init__(self, root):
                self.server = None
            def start(self):
                self.server = True
                return 'http://127.0.0.1:5080'
            def stop(self):
                self.server = None

        def luminance(rgb):
            channels = [value / 255 for value in ((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255)]
            r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        def contrast(dialog, label):
            dialog.resize(380, dialog.sizeHint().height())
            image = dialog.grab().toImage()
            origin = label.mapTo(dialog, QPoint(0, 0))
            values = [luminance(image.pixel(origin.x() + x, origin.y() + y))
                      for x in range(label.width()) for y in range(label.height())]
            return (max(values) + 0.05) / (min(values) + 0.05)

        def assert_dialogs_readable(window):
            prompt = QInputDialog(window)
            prompt.setLabelText('Instance name')
            assert contrast(prompt, prompt.findChild(QLabel)) >= 4.5
            message = QMessageBox(window)
            message.setText('Download and install QuillSail 9.0.0?')
            assert contrast(message, message.findChild(QLabel, 'qt_msgbox_label')) >= 4.5

        root = Path(sys.argv[1]) / 'default'
        registry = root.with_name('default-instances')
        desktop_ui.DesktopRuntime = Runtime
        app = QApplication([])
        # Stand in for the system palette under macOS dark appearance.
        app.setPalette(QPalette(QColor('#323232'), QColor('#1e1e1e')))
        errors = []

        def inspect():
            windows = [w for w in app.topLevelWidgets() if isinstance(w, QMainWindow)]
            if not windows or windows[0].busy or not windows[0].runtime.server:
                return
            timer.stop()
            window = windows[0]
            try:
                # Light is the default even when the system appearance is dark.
                assert app.palette().color(QPalette.ColorRole.Window).name() == '#ffffff'
                assert window.appearance_buttons['light'].isChecked()
                assert window.runtime.appearance == 'light'
                # The bundled display face loads instead of a system fallback.
                assert window.findChild(QLabel, 'masthead').font().family() == 'Amiri'
                # "Quill" is logo purple and "Sail" takes the ink color.
                masthead = window.findChild(QLabel, 'masthead')
                assert '>Quill</span>Sail' in masthead.text() and '#6e4cc2' in masthead.text()
                assert masthead.palette().color(masthead.foregroundRole()).name() == '#000000'
                assert_dialogs_readable(window)
                window.appearance_buttons['dark'].click()
                # Running publications follow, so browser setup matches the launcher.
                assert all(runtime.appearance == 'dark' for runtime in window.runtimes.values())
                assert app.palette().color(QPalette.ColorRole.Window).name() == '#000000'
                assert desktop_ui.saved_appearance(registry) == 'dark'
                assert_dialogs_readable(window)
            except BaseException as exc:
                errors.append(repr(exc))
            window.request_quit()

        timer = QTimer()
        timer.timeout.connect(inspect)
        timer.start(10)
        QTimer.singleShot(10_000, lambda: (errors.append('GUI test timed out'), app.exit(1)))
        assert desktop_ui.run(data_dir=root, open_browser=False) == 0, errors
        assert not errors, errors
    """)
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_closing_the_window_keeps_publications_running_until_quit(tmp_path):
    pytest.importorskip("PySide6")
    script = textwrap.dedent("""
        import sys
        import threading
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMainWindow
        from copydesk import desktop_ui
        from copydesk.launcher import send_command

        root = Path(sys.argv[1]) / 'default'
        registry = root.with_name('default-instances')
        calls, replies, errors, threads = [], {}, [], []
        phase = [0]

        class Runtime:
            def __init__(self, root):
                self.server = None
            def start(self):
                calls.append('start')
                self.server = True
                return 'http://127.0.0.1:5080'
            def stop(self):
                if self.server:
                    calls.append('stop')
                self.server = None

        def ask(command):
            # The launcher answers on the GUI thread, so ask from another one.
            thread = threading.Thread(target=lambda: replies.__setitem__(command, send_command(registry, command)))
            threads.append(thread)
            thread.start()

        desktop_ui.DesktopRuntime = Runtime
        app = QApplication([])

        def inspect():
            try:
                windows = [w for w in app.topLevelWidgets() if isinstance(w, QMainWindow)]
                if not windows or windows[0].busy:
                    return
                window = windows[0]
                if phase[0] == 0 and window.runtime.server:
                    window.keep_running_on_close = True  # As with a Dock or tray icon.
                    window.close()
                    assert window.isHidden() and window.runtime.server and calls == ['start']
                    phase[0] = 1
                    ask('show')
                elif phase[0] == 1 and replies.get('show') == 'ok' and window.isVisible():
                    assert window.quit_button.isEnabled()
                    phase[0] = 2
                    ask('quit')
            except BaseException as exc:
                errors.append(repr(exc))
                app.exit(1)

        timer = QTimer()
        timer.timeout.connect(inspect)
        timer.start(10)
        QTimer.singleShot(10_000, lambda: (errors.append(f'Timed out in phase {phase[0]}'), app.exit(1)))
        assert desktop_ui.run(data_dir=root, open_browser=False) == 0, errors
        for thread in threads:
            thread.join(5)
        assert not errors and phase[0] == 2, errors
        assert replies == {'show': 'ok', 'quit': 'ok'}, replies
        assert calls == ['start', 'stop'], calls
        # The launcher stops listening when it exits.
        assert send_command(registry, 'ping') is None
    """)
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('erase', [False, True])
def test_launcher_deletes_instance_with_explicit_file_choice(tmp_path, erase):
    pytest.importorskip('PySide6')
    script = textwrap.dedent('''
        import sys
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
        from copydesk import desktop_ui, instances

        root = Path(sys.argv[1])
        erase = sys.argv[2] == 'True'
        registry = instances.InstanceRegistry(root / 'registry', default_root=root / 'default')
        item = registry.add('Disposable')
        desktop_ui.default_data_dir = lambda: root / 'default'
        instances.InstanceRegistry = lambda: registry
        class Runtime:
            def __init__(self, root):
                self.root = root
                self.server = None
                self.url = 'http://127.0.0.1:5080'
            def start(self):
                self.server = True
                return 'http://127.0.0.1:5080'
            def stop(self):
                self.server = None
        desktop_ui.DesktopRuntime = Runtime
        def approve(dialog):
            assert 'Remove Disposable' in dialog.text()
            assert not dialog.checkBox().isChecked()
            dialog.checkBox().setChecked(erase)
            return QMessageBox.StandardButton.Ok
        QMessageBox.exec = approve
        errors = []
        def check():
            window = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMainWindow))
            try:
                if window.busy:
                    QTimer.singleShot(20, check)
                    return
                if registry.get('default').id == window.selected_instance.id:
                    window.instance_selector.setCurrentIndex(window.instance_selector.findData(item.id))
                    assert window.delete_instance_button.isEnabled()
                    window.delete_instance_button.click()
                    QTimer.singleShot(20, finish)
            except Exception as exc:
                errors.append(exc)
                window.request_quit()
        def finish():
            window = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMainWindow))
            if window.busy:
                QTimer.singleShot(20, finish)
                return
            try:
                assert registry.list() == [registry.default]
                assert item.root.exists() is not erase
                assert window.selected_instance.id == 'default'
                assert window.delete_instance_button.isEnabled()
            except Exception as exc:
                errors.append(exc)
            window.request_quit()
        app = QApplication([])
        QTimer.singleShot(100, check)
        assert desktop_ui.run(open_browser=False) == 0
        assert not errors, errors
    ''')
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), str(erase)],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('action', ['keep', 'erase', 'cancel'])
def test_delete_running_default_and_reopen_empty_launcher(tmp_path, action):
    pytest.importorskip('PySide6')
    script = textwrap.dedent('''
        import sys
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
        from copydesk import desktop_ui, instances
        from copydesk.desktop import DesktopRuntime

        root, action = Path(sys.argv[1]), sys.argv[2]
        registry = instances.InstanceRegistry(root / 'registry', default_root=root / 'default')
        DesktopRuntime(registry.default.root).initialize()
        desktop_ui.default_data_dir = lambda: registry.default.root
        instances.InstanceRegistry = lambda: registry
        calls, errors = [], []
        class Runtime:
            def __init__(self, root):
                self.root = root
                self.server = None
                self.url = 'http://127.0.0.1:5080'
            def start(self):
                calls.append('start')
                self.server = True
                return self.url
            def stop(self):
                if self.server:
                    calls.append('stop')
                self.server = None
        desktop_ui.DesktopRuntime = Runtime
        original_delete = registry.delete
        def delete(*args, **kwargs):
            # Registry must finish the owned runtime before taking its deletion lock.
            item = original_delete(*args, **kwargs)
            assert calls == ['start', 'stop']
            calls.append('delete')
            return item
        registry.delete = delete
        def confirm(dialog):
            assert 'Default publication' in dialog.text()
            assert dialog.button(QMessageBox.StandardButton.Ok).text() == 'Stop and delete'
            assert calls == ['start']
            dialog.checkBox().setChecked(action == 'erase')
            return QMessageBox.StandardButton.Cancel if action == 'cancel' else QMessageBox.StandardButton.Ok
        QMessageBox.exec = confirm
        app = QApplication([])
        def window():
            return next(w for w in app.topLevelWidgets() if isinstance(w, QMainWindow))
        def inspect():
            w = window()
            if w.busy:
                QTimer.singleShot(20, inspect)
                return
            try:
                assert w.selected_instance.id == 'default'
                assert w.delete_instance_button.isEnabled()
                w.delete_instance_button.click()
                QTimer.singleShot(20, finished)
            except Exception as exc:
                errors.append(exc)
                w.request_quit()
        def finished():
            w = window()
            if w.busy:
                QTimer.singleShot(20, finished)
                return
            try:
                if action == 'cancel':
                    assert calls == ['start'] and w.runtime.server
                    assert registry.list() == [registry.default]
                else:
                    assert calls == ['start', 'stop', 'delete']
                    assert registry.list() == [] and w.runtime is None
                    assert w.status.text() == 'Create or add an instance'
                    assert w.new_instance.isEnabled() and w.add_instance.isEnabled()
                    assert not w.toggle.isEnabled() and not w.open_button.isEnabled()
                    assert not w.files_button.isEnabled() and not w.delete_instance_button.isEnabled()
                    assert registry.default.root.exists() is (action != 'erase')
            except Exception as exc:
                errors.append(exc)
            w.request_quit()
        QTimer.singleShot(100, inspect)
        assert desktop_ui.run(open_browser=False) == 0
        assert not errors, errors
        if action != 'cancel':
            def reopened():
                w = window()
                try:
                    assert w.runtime is None and not w.runtimes
                    assert w.status.text() == 'Create or add an instance'
                    assert calls == ['start', 'stop', 'delete']
                except Exception as exc:
                    errors.append(exc)
                w.request_quit()
            QTimer.singleShot(100, reopened)
            assert desktop_ui.run(open_browser=False) == 0
            assert not errors, errors
            assert registry.list() == []
    ''')
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), action],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('action', ['create', 'add', 'update'])
def test_empty_launcher_supports_new_existing_and_update_actions(tmp_path, action):
    pytest.importorskip('PySide6')
    script = textwrap.dedent('''
        import sys
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMainWindow
        from copydesk import desktop_ui, instances, updater
        from copydesk.desktop import DesktopRuntime
        from copydesk import __version__

        root, action = Path(sys.argv[1]), sys.argv[2]
        registry = instances.InstanceRegistry(root / 'registry', default_root=root / 'default')
        registry.delete('default')
        saved = root / 'saved-publication'
        DesktopRuntime(saved).initialize()
        desktop_ui.default_data_dir = lambda: registry.default.root
        instances.InstanceRegistry = lambda: registry
        starts, errors = [], []
        class Runtime:
            def __init__(self, root):
                self.root, self.server = root, None
                self.url = 'http://127.0.0.1:5080'
            def start(self):
                starts.append(self.root)
                self.server = True
                return self.url
            def stop(self):
                self.server = None
        class Client:
            def check(self, **kwargs):
                return updater.Update(__version__, __version__, 'linux-x86_64', 'beta', '', 0, '')
        desktop_ui.DesktopRuntime = Runtime
        updater.UpdateClient = Client
        QInputDialog.getText = lambda *args: ('Replacement', True)
        QFileDialog.getExistingDirectory = lambda *args: str(saved)
        app = QApplication([])
        def window():
            return next(w for w in app.topLevelWidgets() if isinstance(w, QMainWindow))
        def inspect():
            w = window()
            try:
                assert w.runtime is None and not starts
                w.resize(460, 600)
                w.refresh_button.click()
                assert w.status.text() == 'Create or add an instance'
                if action == 'update':
                    w.update_button.click()
                elif action == 'create':
                    w.new_instance.click()
                else:
                    w.add_instance.click()
                QTimer.singleShot(50, finish)
            except Exception as exc:
                errors.append(exc)
                w.request_quit()
        def finish():
            w = window()
            if w.busy:
                QTimer.singleShot(20, finish)
                return
            try:
                if action == 'update':
                    assert w.runtime is None and not starts
                    assert not w.toggle.isEnabled() and not w.open_button.isEnabled()
                    assert w.new_instance.isEnabled() and w.update_button.isEnabled()
                else:
                    assert w.selected_instance.id == 'replacement'
                    assert w.runtime.server and len(starts) == 1
                    assert starts[0] == (saved if action == 'add' else registry.root / 'publications/replacement')
                    assert w.delete_instance_button.isEnabled()
            except Exception as exc:
                errors.append(exc)
            w.request_quit()
        QTimer.singleShot(100, inspect)
        assert desktop_ui.run(open_browser=False) == 0
        assert not errors, errors
        assert not registry.default.root.exists()
    ''')
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), action],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
