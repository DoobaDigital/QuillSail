"""The terminal must be a full alternative to the desktop window."""
import json
import logging
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import threading
from unittest import mock

import pytest
import requests
from click.testing import CliRunner

from copydesk import cli, installed_command, instances
from copydesk.cli import main
from copydesk.desktop import CONTROL_FILE, CONTROL_HEADER, DesktopRuntime, SharedLogHandler


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(instances, 'default_data_dir', lambda: tmp_path / 'default')
    monkeypatch.setenv('QUILLSAIL_INSTANCE_HOME', str(tmp_path / 'manager'))
    monkeypatch.delenv('SSH_CONNECTION', raising=False)
    return instances.InstanceRegistry()


def stop_when_started(monkeypatch):
    """Let a foreground instance start, then end it as Ctrl+C would."""
    stop = threading.Event()
    started = []
    monkeypatch.setattr('copydesk.cli.Event', lambda: stop)
    original = DesktopRuntime.start
    def start(runtime, **kwargs):
        result = original(runtime, **kwargs)
        started.append(runtime)
        stop.set()
        return result
    monkeypatch.setattr(DesktopRuntime, 'start', start)
    return started


def test_quillsail_alone_prints_help_instead_of_opening_anything(registry):
    result = CliRunner().invoke(main, [])
    assert result.exit_code == 0, result.output
    for command in ('desktop', 'instance', 'update', 'quit'):
        assert re.search(rf'^  {command}\b', result.output, re.MULTILINE)
    assert not registry.default.root.exists()


def test_instance_starts_the_first_publication_as_the_desktop_app_does(registry, monkeypatch):
    started = stop_when_started(monkeypatch)
    result = CliRunner().invoke(main, ['instance', '--no-browser'])
    assert result.exit_code == 0, (result.output, result.exception)
    assert [runtime.root for runtime in started] == [registry.default.root]
    assert re.search(r'^default: http://127\.0\.0\.1:\d+$', result.output, re.MULTILINE)
    assert '/_desktop/open?ticket=' in result.output
    assert 'quillsail instance open default' in result.output
    assert started[0].server is None and instances.running_url(registry.default) == ''
    assert not (registry.default.root / CONTROL_FILE).exists()
    # The log is the same private file the desktop window shows.
    assert stat.S_IMODE((registry.root / 'quillsail.log').stat().st_mode) == 0o600


def test_instance_name_creates_once_then_reuses_and_port_is_remembered(registry, monkeypatch):
    started = stop_when_started(monkeypatch)
    runner = CliRunner()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    result = runner.invoke(main, ['instance', '--name', 'Student Blog', '--port', str(port), '--no-browser'])
    assert result.exit_code == 0, (result.output, result.exception)
    assert f'student-blog: http://127.0.0.1:{port}' in result.output
    item = registry.get('student-blog')
    assert json.loads((item.root / 'desktop.json').read_text())['port'] == port
    for spelling in ('student blog', 'student-blog'):
        result = runner.invoke(main, ['instance', '-n', spelling, '--no-browser'])
        assert result.exit_code == 0, (result.output, result.exception)
    assert [row.id for row in registry.list()] == ['default', 'student-blog']
    assert [runtime.root for runtime in started] == [item.root] * 3


def test_a_port_in_use_is_an_error_when_someone_asked_for_it(registry, monkeypatch, capfd):
    with socket.socket() as taken:
        taken.bind(('127.0.0.1', 0))
        taken.listen()
        port = taken.getsockname()[1]
        result = CliRunner().invoke(main, ['instance', '--port', str(port), '--no-browser'])
    assert result.exit_code == 1
    assert f'Port {port} is already in use' in result.output


def test_data_dir_creates_or_reuses_a_publication_in_that_folder(registry, tmp_path, monkeypatch):
    started = stop_when_started(monkeypatch)
    runner = CliRunner()
    folder = tmp_path / 'my-site'
    for _ in range(2):
        result = runner.invoke(main, ['instance', '--data-dir', str(folder), '--no-browser'])
        assert result.exit_code == 0, (result.output, result.exception)
    assert registry.get('my-site').root == folder.resolve()
    assert [runtime.root for runtime in started] == [folder.resolve()] * 2
    full = tmp_path / 'not-a-publication'
    full.mkdir()
    (full / 'notes.txt').write_text('mine')
    result = runner.invoke(main, ['instance', '--data-dir', str(full), '--no-browser'])
    assert result.exit_code == 1 and 'already contains other files' in result.output


def test_a_bad_saved_port_counts_as_stopped_instead_of_crashing(registry):
    item = registry.add('Team')
    runner = CliRunner()
    for saved in ({'format': 'quillsail.desktop.v1', 'port': 0}, {'format': 'something else', 'port': 5080}, {'format': 'quillsail.desktop.v1'}):
        (item.root / 'desktop.json').write_text(json.dumps(saved))
        assert instances.running_status(item) == {} and instances.running_url(item) == ''
        result = runner.invoke(main, ['instance', 'list'])
        assert result.exit_code == 0 and 'team · Team · Stopped' in result.output
        assert json.loads(runner.invoke(main, ['instance', 'status', item.id, '--json']).output)['running'] is False


def test_a_first_named_instance_is_not_replaced_by_an_empty_default(registry, monkeypatch):
    started = stop_when_started(monkeypatch)
    runner = CliRunner()
    assert runner.invoke(main, ['instance', '--name', 'My publication', '--no-browser']).exit_code == 0
    mine = registry.get('my-publication')
    assert runner.invoke(main, ['instance', '--no-browser']).exit_code == 0
    assert [runtime.root for runtime in started] == [mine.root] * 2
    assert not registry.default.root.exists()
    assert runner.invoke(main, ['instance', 'folder']).output.strip() == str(mine.root)
    # Once the default publication exists, it comes first again, as it does in the app.
    DesktopRuntime(registry.default.root).initialize()
    assert runner.invoke(main, ['instance', 'folder']).output.strip() == str(registry.default.root)


def test_background_does_not_promise_anything_for_an_instance_started_elsewhere(registry, monkeypatch):
    monkeypatch.setattr(instances, 'running_url', lambda item: 'http://127.0.0.1:5999')
    monkeypatch.setattr(instances, 'request_link', lambda item: 'http://127.0.0.1:5999/_desktop/open?ticket=x')
    spawned = []
    monkeypatch.setattr(cli.subprocess, 'Popen', lambda *args, **kwargs: spawned.append(args))
    result = CliRunner().invoke(main, ['instance', '--background', '--no-browser'])
    assert result.exit_code == 0, (result.output, result.exception)
    assert spawned == [] and 'already running' in result.output and 'Running in the background' not in result.output


def test_folder_reports_when_no_file_window_can_open(registry, monkeypatch):
    item = registry.add('Team')
    launched = []
    monkeypatch.setattr(cli.click, 'launch', lambda *args, **kwargs: launched.append(kwargs) or 0)
    monkeypatch.setattr(cli, 'has_display', lambda: False)
    result = CliRunner().invoke(main, ['instance', 'folder', item.id, '--open'])
    assert result.exit_code == 1 and str(item.root) in result.output and "couldn't be opened" in result.output
    assert launched == []
    monkeypatch.setattr(cli, 'has_display', lambda: True)
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert CliRunner().invoke(main, ['instance', 'folder', item.id, '--open']).exit_code == 0
    monkeypatch.setattr(sys, 'platform', 'darwin')
    assert CliRunner().invoke(main, ['instance', 'folder', item.id, '--open']).exit_code == 0
    assert launched == [{'wait': True}, {'wait': False}]


def test_several_processes_can_share_the_log_across_rotation(tmp_path):
    logfile = tmp_path / 'quillsail.log'
    def record(text):
        return logging.LogRecord('copydesk', logging.INFO, __file__, 1, text, None, None)
    handlers = [SharedLogHandler(logfile, maxBytes=200, backupCount=2, encoding='utf-8', delay=True) for _ in range(2)]
    try:
        for number in range(30):
            handlers[number % 2].emit(record(f'line {number:02} ' + 'x' * 40))
            # Neither keeps the file open, so neither can write to a rotated copy.
            assert all(handler.stream is None for handler in handlers)
        current = logfile.read_text()
        assert 'line 29' in current and 'line 28' in current
        assert (tmp_path / 'quillsail.log.1').exists() and (tmp_path / 'quillsail.log.2').exists()
        assert not (tmp_path / 'quillsail.log.3').exists()
        for path in tmp_path.iterdir():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        for handler in handlers:
            handler.close()


def test_options_that_start_an_instance_are_refused_with_another_command(registry):
    result = CliRunner().invoke(main, ['instance', '--name', 'Team', 'list'])
    assert result.exit_code == 2 and "can't be used with `list`" in result.output
    assert registry.list() == [registry.default]


def test_empty_registry_says_how_to_start(registry):
    runner = CliRunner()
    assert runner.invoke(main, ['instance', 'delete', 'default', '--yes']).exit_code == 0
    result = runner.invoke(main, ['instance', '--no-browser'])
    assert result.exit_code == 1 and "quillsail instance --name" in result.output


def test_over_ssh_the_browser_stays_closed_and_the_tunnel_is_explained(registry, monkeypatch):
    stop_when_started(monkeypatch)
    monkeypatch.setenv('SSH_CONNECTION', '100.0.0.1 50000 100.0.0.2 22')
    opened = []
    monkeypatch.setattr(cli.webbrowser, 'open', lambda url: opened.append(url) or True)
    result = CliRunner().invoke(main, ['instance'])
    assert result.exit_code == 0, (result.output, result.exception)
    assert opened == []
    port = re.search(r'127\.0\.0\.1:(\d+)', result.output)[1]
    assert f'ssh -L {port}:127.0.0.1:{port} ' in result.output


def test_the_browser_opens_when_it_can_and_no_tunnel_advice_is_shown(registry, monkeypatch):
    stop_when_started(monkeypatch)
    monkeypatch.setattr(cli, 'has_display', lambda: True)
    opened = []
    monkeypatch.setattr(cli.webbrowser, 'open', lambda url: opened.append(url) or True)
    result = CliRunner().invoke(main, ['instance'])
    assert result.exit_code == 0, (result.output, result.exception)
    assert len(opened) == 1 and '/_desktop/open?ticket=' in opened[0]
    assert 'ssh -L' not in result.output


def test_control_requests_need_the_private_token_and_the_window_keeps_its_own_stop(registry):
    item = registry.add('Team')
    runtime = DesktopRuntime(item.root)
    try:
        runtime.start(with_worker=False)
        token = (item.root / CONTROL_FILE).read_text()
        assert stat.S_IMODE((item.root / CONTROL_FILE).stat().st_mode) == 0o600
        for action in ('link', 'stop'):
            for headers in ({}, {CONTROL_HEADER: 'wrong'}, {CONTROL_HEADER: ''}, {CONTROL_HEADER: 'caf\xe9'.encode('latin-1')}):
                assert requests.post(f'{runtime.url}/_desktop/{action}', headers=headers, timeout=5).status_code == 403
        # Another site can't ask from a visitor's browser, even knowing the address.
        crossed = requests.post(f'{runtime.url}/_desktop/stop', headers={CONTROL_HEADER: token, 'Origin': 'https://example.test'}, timeout=5)
        assert crossed.status_code == 403
        link = instances.request_link(item)
        assert link.startswith(runtime.url + '/_desktop/open?ticket=')
        with requests.Session() as browser:
            assert 'name="code"' not in browser.get(link, timeout=10).text
            assert browser.get(link, timeout=10, allow_redirects=False).status_code == 403
        # Started by the window: the terminal is told where to stop it.
        with pytest.raises(instances.ConfigError, match='running in the QuillSail window'):
            instances.request_stop(item)
        assert runtime.server is not None
        runtime.accepts_stop = True
        assert instances.request_stop(item) is True and runtime.stop_requested.is_set()
    finally:
        runtime.stop()
    assert not (item.root / CONTROL_FILE).exists()
    assert instances.request_stop(item) is False
    with pytest.raises(instances.ConfigError, match="isn't running"):
        instances.request_link(item)


def test_control_routes_are_not_served_on_the_public_listener(registry, monkeypatch):
    item = registry.add('Public')
    runtime = DesktopRuntime(item.root)
    try:
        runtime.start(with_worker=False)
        with runtime.app.app_context():
            runtime.set_public_url('https://news.example.test')
        public = f'http://127.0.0.1:{runtime.public_server.server_port}'
        headers = {'Host': 'news.example.test', 'X-Forwarded-For': '203.0.113.9', CONTROL_HEADER: (item.root / CONTROL_FILE).read_text()}
        for action in ('link', 'stop'):
            assert requests.post(f'{public}/_desktop/{action}', headers=headers, timeout=5).status_code == 404
        status = instances.running_status(item)
        assert status['public_url'] == 'https://news.example.test' and status['public_status'] == 'Offline'
        result = CliRunner().invoke(main, ['instance', 'open', item.id, '--public', '--no-browser'])
        assert result.output.strip() == 'https://news.example.test'
    finally:
        runtime.stop()


def test_a_stop_request_ends_only_that_instance_in_a_shared_terminal(registry, monkeypatch):
    first, second = registry.add('First'), registry.add('Second')
    runtimes = {}
    original = DesktopRuntime.start
    def start(runtime, **kwargs):
        result = original(runtime, **kwargs)
        runtimes[runtime.root] = runtime
        if len(runtimes) == 2:
            def ask():
                assert instances.request_stop(first) is True
                assert instances.wait_until_stopped(first, timeout=20)
                # The other one is still serving until it's asked as well.
                assert instances.running_url(second)
                assert instances.request_stop(second) is True
            threading.Thread(target=ask, daemon=True).start()
        return result
    monkeypatch.setattr(DesktopRuntime, 'start', start)
    result = CliRunner().invoke(main, ['instance', 'run', 'first', 'second', '--no-browser', '--no-worker'])
    assert result.exit_code == 0, (result.output, result.exception)
    assert all(runtime.server is None for runtime in runtimes.values())


def test_status_folder_logs_and_appearance_match_the_window(registry):
    runner = CliRunner()
    item = registry.add('Team News')
    result = runner.invoke(main, ['instance', 'status', 'team news', '--json'])
    details = json.loads(result.output)
    assert details['running'] is False and details['directory'] == str(item.root)
    assert 'Stopped' in runner.invoke(main, ['instance', 'status', item.id]).output
    assert runner.invoke(main, ['instance', 'folder', item.id]).output.strip() == str(item.root)
    assert 'Nothing has been logged' in runner.invoke(main, ['instance', 'logs']).output
    (registry.root / 'quillsail.log').write_text('one\ntwo\nthree\n')
    assert runner.invoke(main, ['instance', 'logs', '-n', '2']).output == 'two\nthree\n'
    assert runner.invoke(main, ['instance', 'logs', '-n', '0']).output == ''
    assert 'Appearance: light' in runner.invoke(main, ['instance', 'appearance']).output
    assert runner.invoke(main, ['instance', 'appearance', 'dark']).exit_code == 0
    assert 'Appearance: dark' in runner.invoke(main, ['instance', 'appearance']).output
    assert runner.invoke(main, ['instance', 'appearance', 'purple']).exit_code == 2
    assert 'Nothing is running' in runner.invoke(main, ['instance', 'stop', '--all']).output
    assert "team-news isn't running" in runner.invoke(main, ['instance', 'stop', 'team-news']).output
    assert "isn't running" in runner.invoke(main, ['instance', 'open', item.id, '--no-browser']).output


def test_setup_follows_the_saved_appearance_in_a_terminal_instance(registry, monkeypatch):
    registry.root.mkdir(parents=True)
    assert CliRunner().invoke(main, ['instance', 'appearance', 'dark']).exit_code == 0
    started = stop_when_started(monkeypatch)
    assert CliRunner().invoke(main, ['instance', '--no-browser']).exit_code == 0
    assert started[0].appearance == 'dark'


def test_logs_follow_prints_new_lines_until_interrupted(registry, monkeypatch):
    registry.root.mkdir(parents=True)
    logfile = registry.root / 'quillsail.log'
    # A byte that isn't valid text must not throw off where following picks up.
    logfile.write_bytes(b'old \xff\n')
    naps = []
    def nap(_seconds):
        naps.append(1)
        if len(naps) == 1:
            with logfile.open('a') as stream:
                stream.write('new\n')
            return
        raise KeyboardInterrupt
    monkeypatch.setattr(cli.time, 'sleep', nap)
    result = CliRunner().invoke(main, ['instance', 'logs', '--follow'])
    assert result.exit_code == 0 and result.output == 'old \ufffd\nnew\n'


def test_several_running_instances_must_be_named(registry, monkeypatch):
    registry.add('First')
    registry.add('Second')
    monkeypatch.setattr(instances, 'running_status', lambda item: {'url': 'http://127.0.0.1:1'})
    monkeypatch.setattr(instances, 'running_url', lambda item: 'http://127.0.0.1:1')
    result = CliRunner().invoke(main, ['instance', 'open'])
    assert result.exit_code == 1 and 'Name the one you mean' in result.output


def test_update_channel_can_be_shown_and_chosen(tmp_path, monkeypatch):
    from copydesk import updater

    monkeypatch.setattr(updater, 'cache_dir', lambda: tmp_path)
    runner = CliRunner()
    assert 'Update channel: beta' in runner.invoke(main, ['update', 'channel']).output
    assert runner.invoke(main, ['update', 'channel', 'stable']).exit_code == 0
    assert 'Update channel: stable' in runner.invoke(main, ['update', 'channel']).output


def test_packaged_update_waits_for_instances_that_share_its_files(registry, tmp_path, monkeypatch):
    from copydesk import update_commands, update_install, updater
    from copydesk.updater import UpdateError

    item = registry.add('Busy')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(updater, 'installation_path', lambda path=None: tmp_path)
    monkeypatch.setattr(update_install, 'read_install', lambda path: {'version': '1.0.0', 'target': 'linux-x86_64'})
    class Client:
        def check(self, **_kwargs):
            return type('Release', (), {'available': True, 'version': '9.0.0', 'release_url': 'https://example.test'})
        def prepare(self, *_args, **_kwargs):
            raise AssertionError('The update must not start while an instance is running.')
    monkeypatch.setattr(updater, 'UpdateClient', Client)
    monkeypatch.setattr(instances, 'running_url', lambda row: 'http://127.0.0.1:1' if row.id == item.id else '')
    with pytest.raises(UpdateError, match='Stop these instances before updating: busy'):
        update_commands.desktop_update(False, None, 'beta', True)


def test_desktop_explains_itself_without_a_graphical_session(registry, monkeypatch):
    monkeypatch.setattr(cli, 'has_display', lambda: False)
    result = CliRunner().invoke(main, ['desktop'])
    assert result.exit_code == 1 and 'quillsail instance' in result.output


def test_desktop_passes_its_options_to_the_window(registry, monkeypatch):
    from copydesk import desktop_ui

    monkeypatch.setattr(cli, 'has_display', lambda: True)
    calls = []
    monkeypatch.setattr(desktop_ui, 'run', lambda **kwargs: calls.append(kwargs) or 0)
    assert CliRunner().invoke(main, ['--instance', 'default', 'desktop', '--no-browser']).exit_code == 0
    assert calls == [{'data_dir': None, 'instance_id': 'default', 'open_browser': False}]


def test_packaged_desktop_starts_a_separate_window_process(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'has_display', lambda: True)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    calls = []
    monkeypatch.setattr(cli, 'open_packaged_window', calls.append)
    runner = CliRunner()
    assert runner.invoke(main, ['desktop']).exit_code == 0
    assert runner.invoke(main, ['--instance', 'default', 'desktop', '--no-browser']).exit_code == 0
    assert runner.invoke(main, ['desktop', '--data-dir', str(tmp_path / 'other')]).exit_code == 0
    assert calls == [[], ['--instance', 'default', '--no-browser'], ['--data-dir', str((tmp_path / 'other').resolve())]]
    result = runner.invoke(main, ['--instance', 'missing', 'desktop'])
    assert result.exit_code == 1 and 'No instance named' in result.output


@pytest.mark.parametrize('platform, expected', [
    ('linux', lambda exe, app: [exe, '--no-browser']),
    ('darwin', lambda exe, app: ['open', '-a', app, '--args', '--no-browser']),
])
def test_opening_the_packaged_window_survives_closing_the_terminal(monkeypatch, tmp_path, platform, expected):
    from copydesk import updater

    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setattr(updater, 'installation_path', lambda: tmp_path)
    seen = []
    monkeypatch.setattr(cli.subprocess, 'Popen', lambda command, **kwargs: seen.append((command, kwargs)))
    monkeypatch.setattr(cli.subprocess, 'run', lambda command, **kwargs: seen.append((command, kwargs)))
    cli.open_packaged_window(['--no-browser'])
    assert seen[0][0] == expected(sys.executable, str(tmp_path))
    if platform == 'linux':
        assert seen[0][1]['start_new_session'] is True and seen[0][1]['stdout'] == subprocess.DEVNULL


def test_the_packaged_app_runs_commands_only_when_the_installed_command_asks(registry, monkeypatch, capsys):
    from copydesk import desktop_ui

    monkeypatch.setattr(sys, 'argv', ['QuillSail', 'cli', 'instance', 'list', '--json'])
    with pytest.raises(SystemExit) as exit_info:
        desktop_ui.main()
    assert exit_info.value.code == 0
    assert json.loads(capsys.readouterr().out)[0]['id'] == 'default'
    monkeypatch.setattr(sys, 'argv', ['QuillSail', 'cli'])
    with pytest.raises(SystemExit) as exit_info:
        desktop_ui.main()
    assert exit_info.value.code == 0 and 'Usage: quillsail' in capsys.readouterr().out
    # Opening from a menu or the Finder passes nothing, and still opens the window.
    opened = []
    monkeypatch.setattr(desktop_ui, 'run', lambda **kwargs: opened.append(kwargs) or 0)
    monkeypatch.setattr(sys, 'argv', ['QuillSail'])
    with pytest.raises(SystemExit):
        desktop_ui.main()
    assert opened == [{'data_dir': None, 'instance_id': None, 'open_browser': True}]


@pytest.mark.parametrize('attached', [True, False])
def test_windows_console_fills_only_missing_streams(monkeypatch, attached):
    from copydesk import desktop_ui

    kernel32 = type('Kernel32', (), {'AttachConsole': staticmethod(lambda _process: attached)})
    monkeypatch.setattr('ctypes.windll', type('Windll', (), {'kernel32': kernel32}), raising=False)
    opened = []
    monkeypatch.setattr('builtins.open', lambda path, *_args, **_kwargs: opened.append(path) or path)
    redirected = object()
    monkeypatch.setattr(sys, 'stdin', None)
    monkeypatch.setattr(sys, 'stdout', redirected)
    monkeypatch.setattr(sys, 'stderr', None)
    desktop_ui.attach_windows_console()
    # Output sent to a file or pipe must not be pulled back to the console.
    assert sys.stdout is redirected
    if attached:
        assert opened == ['CONIN$', 'CONOUT$'] and sys.stdin == 'CONIN$' and sys.stderr == 'CONOUT$'
    else:
        assert opened == [] and sys.stdin is None and sys.stderr is None


def test_packaged_serve_does_not_try_to_restart_itself(tmp_path, monkeypatch):
    import flask

    runner = CliRunner()
    site = tmp_path / 'site'
    assert runner.invoke(main, ['init', '--dir', str(site), '--site-name', 'Test', '--base-url', 'http://localhost:5055',
                                '--admin-name', 'Editor', '--admin-email', 'editor@example.edu',
                                '--admin-password', 'correct-horse-battery-123', '--yes']).exit_code == 0
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    seen = {}
    monkeypatch.setattr(flask.Flask, 'run', lambda self, **kwargs: seen.update(kwargs))
    result = runner.invoke(main, ['--config', str(site / 'copydesk.toml'), 'serve', '--no-worker'])
    assert result.exit_code == 0, (result.output, result.exception)
    assert seen['use_reloader'] is False


def test_a_packaged_command_cleans_its_environment_before_anything_starts(monkeypatch, tmp_path):
    from copydesk import desktop_ui

    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(installed_command, 'refresh_installed_command', lambda: None)
    monkeypatch.setattr(sys, 'argv', ['QuillSail', 'cli', '--version'])
    bundled = {'_PYI_APPLICATION_HOME_DIR': str(tmp_path), 'LD_LIBRARY_PATH': str(tmp_path), 'LD_LIBRARY_PATH_ORIG': '/usr/lib/original'}
    with mock.patch.dict(os.environ, bundled), pytest.raises(SystemExit):
        try:
            desktop_ui.main()
        finally:
            # Everything started from here inherits this, including this app again.
            assert os.environ['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
            assert os.environ['LD_LIBRARY_PATH'] == '/usr/lib/original'
            assert '_PYI_APPLICATION_HOME_DIR' not in os.environ
    assert cli.own_command() == [sys.executable, 'cli']


OLD_POSIX = """#!/bin/sh
# Installed by the QuillSail installer. Opens the QuillSail desktop app.
# Remove it with: curl -fsSL https://quillsail.blog/install.sh | bash -s -- --uninstall
app='/opt/QuillSail'
executable='{executable}'
for argument in "$@"; do
  case "$argument" in
    -h|--help|--version|--check-updates|--update|--smoke-test|--smoke-test-gui) exec "$executable" "$@" ;;
  esac
done
# Keep QuillSail running after this terminal closes.
nohup "$executable" "$@" >/dev/null 2>&1 </dev/null &
"""
OLD_WINDOWS = ('@echo off\r\nrem Installed by the QuillSail installer. Opens the QuillSail desktop app.\r\n'
               'rem Remove it with: x\r\nstart "" "%LOCALAPPDATA%\\Programs\\QuillSail\\QuillSail.exe" %*\r\n')


def test_commands_from_older_installers_are_rewritten():
    target, text = installed_command.updated_command(OLD_POSIX.format(executable='/opt/QuillSail/QuillSail'))
    assert target == '/opt/QuillSail/QuillSail'
    assert text == ("#!/bin/sh\n# Installed by the QuillSail installer. Runs the quillsail command from the app.\n"
                    "# Remove it with: curl -fsSL https://quillsail.blog/install.sh | bash -s -- --uninstall\n"
                    "executable='/opt/QuillSail/QuillSail'\nexec \"$executable\" cli \"$@\"\n")
    target, text = installed_command.updated_command(OLD_WINDOWS)
    assert target == '%LOCALAPPDATA%\\Programs\\QuillSail\\QuillSail.exe'
    assert text.endswith('"%LOCALAPPDATA%\\Programs\\QuillSail\\QuillSail.exe" cli %*\r\n') and 'start ""' not in text
    assert installed_command.updated_command('#!/bin/sh\necho the Python package\n') is None
    assert installed_command.updated_command(text) is None


@pytest.mark.skipif(sys.platform == 'win32', reason='the fake command is a shell script')
def test_starting_the_app_repairs_only_its_own_command(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    command = home / '.local/bin/quillsail'
    command.parent.mkdir(parents=True)
    app = tmp_path / 'QuillSail'
    app.write_text('#!/bin/sh\nprintf "%s " "$@"\n')
    app.chmod(0o755)
    monkeypatch.setattr(installed_command.Path, 'home', lambda: home)
    monkeypatch.setenv('PATH', str(tmp_path / 'empty'))
    monkeypatch.setattr(sys, 'executable', str(app))

    command.write_text(OLD_POSIX.format(executable=tmp_path / 'another-copy'))
    (tmp_path / 'another-copy').write_text('')
    original = command.read_text()
    installed_command.refresh_installed_command()
    assert command.read_text() == original

    command.write_text('#!/bin/sh\necho the Python package\n')
    installed_command.refresh_installed_command()
    assert 'Python package' in command.read_text()

    command.write_text(OLD_POSIX.format(executable=app))
    command.chmod(0o755)
    installed_command.refresh_installed_command()
    assert stat.S_IMODE(command.stat().st_mode) == 0o755
    output = subprocess.run([str(command), 'instance', 'list'], capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'})
    assert output.stdout == 'cli instance list '
    assert [path.name for path in command.parent.iterdir()] == ['quillsail']
    rewritten = command.read_text()
    installed_command.refresh_installed_command()
    assert command.read_text() == rewritten


@pytest.fixture
def isolated(tmp_path):
    """Run the real command as separate processes, in a home folder of its own."""
    home = tmp_path / 'home'
    home.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith(('COPYDESK_', 'SSH_'))}
    env.update(HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(home / 'local'), XDG_DATA_HOME=str(home / 'data'),
               QUILLSAIL_INSTANCE_HOME=str(home / 'manager'))
    def run(*arguments, check=True):
        result = subprocess.run([sys.executable, '-m', 'copydesk', *arguments], env=env, cwd=tmp_path,
                                capture_output=True, text=True, timeout=180)
        assert not check or result.returncode == 0, result.stdout + result.stderr
        return result
    run.env, run.home, run.cwd = env, home, tmp_path
    yield run
    run('instance', 'stop', '--all', check=False)


def test_background_instance_survives_setup_stop_and_delete_from_other_commands(isolated):
    run = isolated
    started = run('instance', '--name', 'Student Blog', '--background', '--no-browser')
    assert 'student-blog: http://127.0.0.1:' in started.stdout and 'quillsail instance stop' in started.stdout
    first_link = re.search(r'^Open setup/dashboard: (\S+)$', started.stdout, re.MULTILINE)[1]

    details = json.loads(run('instance', 'status', '--json').stdout)
    assert details['id'] == 'student-blog' and details['running'] is True
    url = details['url']
    assert requests.get(url + '/healthz', timeout=10).json()['database'] == 'ok'
    # Starting it again finds the running one, like a second launch of the app.
    again = run('instance', '-n', 'Student Blog', '--no-browser')
    assert 'already running' in again.stdout and 'Press Ctrl+C' not in again.stdout

    # A link expires quickly, so another terminal can ask for a new one.
    link = re.search(r'^Open setup/dashboard: (\S+)$', run('instance', 'open', '--no-browser').stdout, re.MULTILINE)[1]
    assert link != first_link
    with requests.Session() as browser:
        browser.trust_env = False
        setup = browser.get(link, timeout=15)
        assert setup.status_code == 200 and 'name="code"' not in setup.text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', setup.text)[1]
        dashboard = browser.post(url + '/setup/', data={'csrf_token': csrf, 'site_name': 'Student Blog', 'site_mode': 'hybrid',
                                 'display_name': 'Owner', 'email': 'owner@example.test',
                                 'password': 'synthetic-terminal-owner-123'}, timeout=30)
        assert dashboard.status_code == 200 and dashboard.url == url + '/dashboard/'

    # No link that could sign someone in may end up in the log.
    assert 'ticket=' not in (run.home / 'manager/quillsail.log').read_text()
    folder = run('instance', 'folder').stdout.strip()
    assert folder.endswith('student-blog')

    stopped = run('instance', 'stop', 'student-blog')
    assert 'Stopped student-blog' in stopped.stdout
    assert json.loads(run('instance', 'status', 'student-blog', '--json').stdout)['running'] is False

    # Its account survives a restart, and deleting a running instance stops it first.
    run('instance', 'run', 'student-blog', '--background', '--no-browser')
    deleted = run('instance', 'delete', 'student-blog', '--delete-data', '--yes')
    assert 'permanently deleted' in deleted.stdout
    assert not os.path.exists(folder)


def test_background_failure_points_to_the_log(isolated):
    run = isolated
    run('instance', 'create', 'Broken')
    registry = json.loads((run.home / 'manager/instances.json').read_text())
    folder = next(row['directory'] for row in registry['instances'] if row['id'] == 'broken')
    with open(os.path.join(folder, 'copydesk.toml'), 'w') as handle:
        handle.write('this is not valid toml =')
    result = run('instance', 'run', 'broken', '--background', '--no-browser', check=False)
    assert result.returncode == 1 and 'quillsail instance logs' in result.stderr
    assert 'ERROR' in run('instance', 'logs').stdout


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows has no SIGHUP')
def test_nohup_keeps_an_instance_running_when_the_terminal_closes(isolated):
    run = isolated
    process = subprocess.Popen([sys.executable, '-m', 'copydesk', 'instance', '--no-browser'], env=run.env, cwd=run.cwd,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN))
    try:
        for line in process.stdout:
            if 'Press Ctrl+C' in line:
                break
        process.send_signal(signal.SIGHUP)
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=2)
        assert json.loads(run('instance', 'status', '--json').stdout)['running'] is True
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=60) == 0
    finally:
        if process.poll() is None:
            process.kill()


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows has no SIGHUP')
@pytest.mark.parametrize('name', ['SIGHUP', 'SIGTERM', 'SIGINT'])
def test_closing_the_terminal_finishes_work_and_stops_cleanly(isolated, name):
    run = isolated
    process = subprocess.Popen([sys.executable, '-m', 'copydesk', 'instance', '--no-browser'], env=run.env, cwd=run.cwd,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        lines = []
        for line in process.stdout:
            lines.append(line)
            if 'Press Ctrl+C' in line:
                break
        assert any('Press Ctrl+C' in line for line in lines), lines
        assert json.loads(run('instance', 'status', '--json').stdout)['running'] is True
        process.send_signal(getattr(signal, name))
        assert process.wait(timeout=60) == 0
    finally:
        if process.poll() is None:
            process.kill()
    details = json.loads(run('instance', 'status', '--json').stdout)
    assert details['running'] is False
    assert not os.path.exists(os.path.join(details['directory'], CONTROL_FILE))
