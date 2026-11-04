"""Hosting checks use synthetic accounts, fake DNS and mocked provider calls only."""
import json
from datetime import timedelta

import pytest
import responses
from lxml import html
from sqlalchemy import select, text
from werkzeug.test import Client as WSGIClient
from werkzeug.wrappers import Response

from copydesk import cloudflare, domains, edge, launch, migrate, settings
from copydesk.db import db, make_engine
from copydesk.desktop import DesktopRuntime, PublicRequests
from copydesk.models import (
    AuditEntry,
    EdgeReceipt,
    HostingConnection,
    Job,
    ManagedRecord,
    Subscriber,
)
from copydesk.utils import utcnow


def soon(app):
    with app.app_context():
        settings.set_value('launch.state', 'soon')
        db.session.commit()


@pytest.mark.parametrize('path', ['/articles', '/issues', '/search', '/write/', '/competitions/', '/api/v1/articles', '/a-private-draft'])
def test_launch_gate_blocks_content(app, client, path):
    soon(app)
    response = client.get(path)
    assert response.status_code == 302
    assert response.location == '/'


@pytest.mark.parametrize('path', ['/feed.xml', '/sitemap.xml'])
def test_launch_gate_hides_discovery(app, client, path):
    soon(app)
    assert client.get(path).status_code == 404


def test_existing_installs_stay_live(app, client):
    with app.app_context():
        assert not launch.is_soon()
    assert b'Launching soon' not in client.get('/').data


def test_launch_permissions_csrf_audit_and_hook(app, client, editor_client):
    events = []
    app.extensions['copydesk'].hooks.on('publication.launched', lambda **event: events.append(event))
    assert editor_client.post('/dashboard/launch', data={'action': 'soon'}).status_code == 400
    response = editor_client.post('/dashboard/launch', data={'action': 'soon', 'csrf_token': 'test-csrf'})
    assert response.status_code == 302 and events[0]['new'] == 'soon'
    with app.app_context():
        assert db.session.scalar(select(AuditEntry).where(AuditEntry.action == 'publication.launched'))
    assert b'Readers see the launching-soon page.' in editor_client.get('/').data
    anonymous = app.test_client()
    assert b'Launching soon' in anonymous.get('/').data
    assert b'name="email"' not in anonymous.get('/').data
    assert anonymous.post('/dashboard/launch', data={'action': 'live'}).status_code == 400


def test_launch_gate_allows_login_health_subscriber_pages(app, client):
    soon(app)
    for path in ('/', '/healthz', '/robots.txt', '/login', '/forgot-password', '/subscribe', '/subscribe/thanks'):
        assert client.get(path).status_code == 200, path
    assert client.get('/unsubscribe/not-a-real-token').status_code == 404


def test_health_identity_stable_and_not_a_secret(app, client):
    first = client.get('/healthz').json['instance_id']
    assert len(first) == 32
    assert client.get('/healthz').json['instance_id'] == first


def test_public_listener_rejects_peers_hosts_and_missing_visitor():
    app = PublicRequests(lambda env, start: Response(env['REMOTE_ADDR'] + ' ' + env['wsgi.url_scheme'])(env, start), 'https://news.example.test')
    client = WSGIClient(app, Response)
    kwargs = {'base_url': 'http://news.example.test', 'environ_overrides': {'REMOTE_ADDR': '127.0.0.1'}}
    assert client.get('/', **kwargs).status_code == 400
    assert client.get('/', headers={'X-Forwarded-For': '198.51.100.3'}, **kwargs).text == '198.51.100.3 https'
    assert client.get('/', base_url='http://evil.example.test', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).status_code == 404
    assert client.get('/', base_url='http://news.example.test', environ_overrides={'REMOTE_ADDR': '198.51.100.3'}).status_code == 404


@pytest.mark.parametrize('mode', ['newsletter', 'blog', 'hybrid'])
def test_desktop_public_port_blocks_every_private_endpoint_and_keeps_local_cookie(tmp_path, mode):
    import requests

    from copydesk import seed, workflow
    from copydesk.models import Tag
    from copydesk.views.setup import create_admin

    runtime = DesktopRuntime(tmp_path / 'publication')
    runtime.start(with_worker=False)
    try:
        with runtime.app.app_context():
            seed.seed('Synthetic publication')
            owner = create_admin(email='owner@example.test', name='Owner', password='synthetic-test-password')
            settings.set_value('site.mode', mode)
            settings.set_value('blog.competitions_enabled', True)
            article = workflow.create_draft(owner, 'A public desktop post')
            workflow.save(article, owner, title=article.title, subtitle='', body='Public post text ' * 20)
            article.status, article.published_at = 'published', utcnow()
            article.tags.append(Tag(name='Desktop tag', slug='desktop-tag'))
            slug = article.slug
            db.session.commit()
        runtime.set_public_url('https://news.example.test')
        local = runtime.app.test_client()
        response = local.get('/login', base_url=runtime.url)
        assert response.status_code == 200
        assert 'Secure;' not in response.headers.get('Set-Cookie', '')
        root = f'http://127.0.0.1:{runtime.public_server.server_port}'
        headers = {'Host': 'news.example.test', 'X-Forwarded-For': '198.51.100.5'}
        for path in ('/dashboard/', '/login', '/setup/', '/_desktop/open', '/_desktop/status', '/api/v1/articles', '/write/', '/account/', '/competitions/'):
            assert requests.get(root + path, headers=headers, allow_redirects=False, timeout=3).status_code == 404, path
        assert requests.get(root + '/healthz', headers=headers, timeout=3).status_code == 200
        for path in ('/', f'/articles/{slug}/', '/tags/desktop-tag/', '/issues/feed.xml', '/favicon.svg'):
            response = requests.get(root + path, headers=headers, timeout=3)
            assert response.status_code == 200, path
            if path.endswith('.xml') or path.endswith('.svg'):
                continue
            page = html.fromstring(response.content)
            hrefs = page.xpath('//a/@href')
            assert not any(href.startswith(('/login', '/join', '/write/', '/competitions/')) for href in hrefs)
            # Walk the generated reader links, including tags and feed discovery.
            for href in set(hrefs + page.xpath('//link[@rel="alternate"]/@href')):
                if href.startswith('/') and not href.startswith('//'):
                    linked = requests.get(root + href, headers=headers, timeout=3)
                    assert linked.status_code == 200, (path, href)
        # URL generation outside requests must still work in worker/email jobs.
        with runtime.app.app_context():
            from copydesk.helpers import external_url

            assert external_url('public.home') == 'https://news.example.test/'
        runtime.stop()
        runtime.start(with_worker=False)
        assert runtime.public_url == 'https://news.example.test'
        assert runtime.url.startswith('http://127.0.0.1:')
    finally:
        runtime.stop()


@pytest.mark.parametrize('value', ['http://news.example.test', 'https://user:password@news.example.test', 'https://127.0.0.1', 'https://news.example.test/admin', 'https://news.example.test/?token=secret'])
def test_public_address_validation(value):
    with pytest.raises(domains.DomainProblem):
        domains.public_url(value)


def test_dns_results_and_errors(monkeypatch):
    spec = domains.RecordSpec('news.example.test', 'CNAME', 'target.example.test')
    for values, status in [([], 'Missing'), (['elsewhere.example.test'], 'Different'), (['target.example.test'], 'Found')]:
        monkeypatch.setattr(domains, 'authoritative_values', lambda *_, v=values: v)
        assert domains.check_record(spec)['status'] == status
    def fail(*_):
        raise domains.DomainProblem('Timeout')
    monkeypatch.setattr(domains, 'authoritative_values', fail)
    assert domains.check_record(spec)['status'] == 'Unknown'


@pytest.mark.parametrize(('values', 'expected'), [
    ([], 'v=spf1 include:sender.example.test ~all'),
    (['v=spf1 ip4:192.0.2.1 -all'], 'v=spf1 ip4:192.0.2.1 include:sender.example.test -all'),
    (['v=spf1  include:sender.example.test  ~all'], 'v=spf1  include:sender.example.test  ~all'),
    (['unrelated verification', 'v=spf1 ?all'], 'v=spf1 include:sender.example.test ?all'),
])
def test_spf_preserves_existing_policy(values, expected):
    assert domains.merge_spf(values, 'sender.example.test', lambda *_: ['v=spf1 -all']) == expected


def test_spf_refuses_multiple_redirect_cycles_and_budget():
    for values in (['v=spf1 -all', 'v=spf1 ~all'], ['v=spf1 redirect=other.example.test']):
        with pytest.raises(domains.DomainProblem):
            domains.merge_spf(values, 'sender.example.test')
    with pytest.raises(domains.DomainProblem):
        domains.merge_spf([], 'sender.example.test', lambda *_: ['v=spf1 include:sender.example.test -all'])
    policy = 'v=spf1 ' + ' '.join('include:d' + str(i) + '.example.test' for i in range(10)) + ' -all'
    with pytest.raises(domains.DomainProblem):
        domains.merge_spf([policy], 'sender.example.test', lambda *_: ['v=spf1 -all'])
    long = 'v=spf1 ' + ' '.join('ip4:192.0.2.1' for _ in range(30)) + ' -all'
    result = domains.merge_spf([long], 'sender.example.test', lambda *_: ['v=spf1 -all'])
    assert len(result) > 255 and result.endswith('-all')


def test_dkim_parser_and_outside_domain_refused():
    assert domains.parse_dkim('selector._domainkey.example.test TXT "v=DKIM1; p=synthetic"', 'example.test')[0].value == 'v=DKIM1; p=synthetic'
    with pytest.raises(domains.DomainProblem):
        domains.parse_dkim('selector._domainkey.other.test TXT v=DKIM1; p=synthetic', 'example.test')


@responses.activate
def test_cloudflare_credentials_encrypted_and_authorization_sanitized(app):
    with app.app_context():
        cloudflare.connect('synthetic-private-api-token')
        db.session.commit()
        row = db.session.get(HostingConnection, 1)
        assert 'synthetic-private-api-token' not in row.payload
        assert all('token' not in json.dumps(job.payload) for job in db.session.scalars(select(Job)))
        responses.get(cloudflare.API + '/user/tokens/verify', status=401, json={'error': 'synthetic-private-api-token'})
        with pytest.raises(domains.DomainProblem, match='authorization') as exc:
            cloudflare.verify_token({})
        assert 'synthetic-private-api-token' not in str(exc.value)
        assert db.session.get(HostingConnection, 1).status == 'authorization_required'


def test_dns_undo_restores_exact_value_and_refuses_external_changes(app, monkeypatch):
    class Fake:
        value = 'v=spf1  include:old.example.test include:new.example.test -all'
        calls = []
        def pages(self, *_args, **_kwargs):
            return [{'id': 'owned', 'type': 'TXT', 'content': self.value}]
        def call(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
    with app.app_context():
        old = 'v=spf1  include:old.example.test -all'
        record = ManagedRecord(zone_id='zone', provider_id='owned', name='example.test', type='TXT', value=Fake.value, previous=old)
        db.session.add(record)
        db.session.commit()
        monkeypatch.setattr(domains, 'authoritative_values', lambda *_: [old])
        fake = Fake()
        fake.value = 'changed elsewhere'
        with pytest.raises(domains.DomainProblem):
            cloudflare.undo_record(fake, record)
        assert not fake.calls
        fake.value = record.value
        cloudflare.undo_record(fake, record)
        assert fake.calls[0][0] == 'PATCH'
        assert fake.calls[0][2]['json']['content'] == old


def test_edge_replay_receipt_and_received_time(app):
    with app.app_context():
        subscriber = Subscriber(email='synthetic@example.test', status='active', token='synthetic-token-not-real')
        db.session.add(subscriber)
        db.session.commit()
        received = (utcnow() - timedelta(days=4)).isoformat() + 'Z'
        entry = {'action': 'unsubscribe', 'token': subscriber.token, 'received': received}
        edge.replay_entry('action:synthetic', entry)
        db.session.commit()
        assert subscriber.status == 'unsubscribed'
        assert subscriber.unsubscribed_at < utcnow() - timedelta(days=3)
        edge.replay_entry('action:synthetic', entry)
        db.session.commit()
        assert len(db.session.scalars(select(EdgeReceipt)).all()) == 1
        # No invalid token can unsubscribe another reader.
        subscriber.status = 'active'
        edge.replay_entry('action:invalid', {**entry, 'token': 'not-a-subscriber-token'})
        db.session.commit()
        assert subscriber.status == 'active'


def test_hosting_migration_upgrade_preserves_existing_data(tmp_path):
    engine = make_engine(f'sqlite:///{tmp_path}/upgrade.db')
    try:
        migrate.upgrade(engine, '0006')
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO settings (key, value, updated_at) VALUES ('site.name', '\"Existing publication\"', CURRENT_TIMESTAMP)"))
        migrate.upgrade(engine)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT value FROM settings WHERE key = 'site.name'")).scalar() == '"Existing publication"'
            assert conn.execute(text("SELECT value FROM settings WHERE key = 'launch.state'")).scalar() is None
            assert conn.execute(text("SELECT value FROM settings WHERE key = 'system.instance_id'")).scalar()
            for table in ('hosting_connection', 'managed_records', 'edge_receipts'):
                assert conn.execute(text(f'SELECT count(*) FROM {table}')).scalar() == 0
    finally:
        engine.dispose()


@responses.activate
def test_cloudflare_provision_resumes_without_duplicate_tunnel_or_dns(app, monkeypatch):
    with app.app_context():
        cloudflare.save({'token': 'synthetic-token', 'zone': 'zone', 'hostname': 'news.example.test'}, 'provisioning')
        db.session.commit()
        host = 'news.example.test'
        marker = 'Managed by QuillSail ' + domains.instance_id()
        account = cloudflare.API + '/accounts/account'
        zone = cloudflare.API + '/zones/zone'
        dns_record = {'id': 'record', 'name': host, 'type': 'CNAME', 'content': 'tunnel.cfargotunnel.com', 'comment': marker}
        responses.get(zone, json={'success': True, 'result': {'account': {'id': 'account'}}})
        responses.get(zone + '/dns_records', json={'success': True, 'result': []})
        responses.get(account + '/cfd_tunnel', json={'success': True, 'result': []})
        responses.post(account + '/cfd_tunnel', json={'success': True, 'result': {'id': 'tunnel'}})
        responses.put(account + '/cfd_tunnel/tunnel/configurations', json={'success': True, 'result': {}})
        responses.post(zone + '/dns_records', json={'success': True, 'result': dns_record})
        responses.get(account + '/cfd_tunnel/tunnel/token', status=503, json={'success': False})
        with pytest.raises(domains.DomainProblem):
            cloudflare.provision({})
        assert db.session.get(HostingConnection, 1)
        assert len(db.session.scalars(select(ManagedRecord)).all()) == 1
        responses.replace(responses.GET, zone + '/dns_records', json={'success': True, 'result': [dns_record]})
        responses.replace(responses.GET, account + '/cfd_tunnel/tunnel/token', json={'success': True, 'result': 'synthetic-tunnel-token'})
        cloudflare.provision({})
        db.session.commit()
        assert sum(call.request.method == 'POST' and call.request.url == account + '/cfd_tunnel' for call in responses.calls) == 1
        assert sum(call.request.method == 'POST' and call.request.url == zone + '/dns_records' for call in responses.calls) == 1
        row, data = cloudflare.connection()
        assert data['tunnel_token'] == 'synthetic-tunnel-token'
        assert 'synthetic-tunnel-token' not in row.payload


@responses.activate
def test_cloudflare_existing_record_and_pending_zone_stop_without_writes(app):
    with app.app_context():
        cloudflare.save({'token': 'synthetic-token', 'zone': 'zone', 'hostname': 'news.example.test'}, 'provisioning')
        db.session.commit()
        responses.get(cloudflare.API + '/zones/zone', json={'success': True, 'result': {'account': {'id': 'account'}}})
        responses.get(cloudflare.API + '/zones/zone/dns_records', json={'success': True, 'result': [{'id': 'unrelated', 'name': 'news.example.test', 'type': 'A', 'content': '192.0.2.1'}]})
        with pytest.raises(domains.DomainProblem, match='already uses'):
            cloudflare.provision({})
        assert all(call.request.method == 'GET' for call in responses.calls)
        settings.set_value('hosting.zones', [{'id': 'pending', 'name': 'example.test', 'status': 'pending', 'type': 'full'}])
        with pytest.raises(domains.DomainProblem, match='active domain'):
            cloudflare.choose('pending', 'news')


def test_oauth_pkce_browser_binding_single_use_and_credential_storage(app, editor_client):
    from urllib.parse import parse_qs, urlsplit

    from copydesk import hosting_oauth
    from copydesk.models import HostingOAuthFlow, User

    app.extensions['copydesk'].config.base_url = 'https://publication.example.test'
    app.extensions['copydesk'].config.oauth_clients['cloudflare'] = {'client_id': 'synthetic-public-client',
        'scopes': 'synthetic-approved-scope offline_access', 'relay_url': 'https://relay.example.test/oauth/cloudflare/callback'}
    response = editor_client.post('/dashboard/domain', data={'csrf_token': 'test-csrf', 'action': 'oauth'})
    assert response.status_code == 302
    params = parse_qs(urlsplit(response.location).query)
    assert params['code_challenge_method'] == ['S256']
    assert 'code_verifier' not in params
    saved_state = params['state'][0]
    with app.app_context():
        flow = db.session.scalar(select(HostingOAuthFlow))
        assert flow and 'verifier' not in flow.payload
        user = db.session.get(User, flow.user_id)
        with app.test_request_context('/dashboard/domain/oauth/callback'), pytest.raises(domains.DomainProblem, match='browser'):
            hosting_oauth.finish(user, saved_state, 'synthetic-code')
    with responses.RequestsMock() as mock:
        mock.post(hosting_oauth.TOKEN, json={'access_token': 'synthetic-oauth-access',
            'refresh_token': 'synthetic-oauth-refresh', 'expires_in': 3600})
        response = editor_client.get('/dashboard/domain/oauth/callback', query_string={'state': saved_state, 'code': 'synthetic-code'})
        assert response.status_code == 302 and response.headers['Referrer-Policy'] == 'no-referrer'
        assert 'code_verifier=' in mock.calls[0].request.body
        # Browser state has been consumed; the callback cannot exchange again.
        editor_client.get('/dashboard/domain/oauth/callback', query_string={'state': saved_state, 'code': 'synthetic-code'})
        assert len(mock.calls) == 1
    with app.app_context():
        row = db.session.get(HostingConnection, 1)
        assert row and 'synthetic-oauth-access' not in row.payload
        assert db.session.scalar(select(HostingOAuthFlow)) is None


def test_hosting_dashboard_forms_render_with_accessible_labels(editor_client):
    for path in ('/dashboard/domain', '/dashboard/launch'):
        response = editor_client.get(path)
        assert response.status_code == 200
        assert b'name="csrf_token"' in response.data
        assert b'<label' in response.data


def test_tunnel_supervision_uses_environment_and_stops_fake_process(tmp_path, monkeypatch):
    import subprocess
    import sys
    import time

    from copydesk.tunnel import Tunnel

    script = tmp_path / 'fake_cloudflared.py'
    script.write_text('''import os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
assert os.environ['TUNNEL_TOKEN'] == 'synthetic-tunnel-secret'
assert 'synthetic-tunnel-secret' not in ' '.join(sys.argv)
port = int(sys.argv[sys.argv.index('--metrics') + 1].split(':')[-1])
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == '/ready' else 404)
        self.end_headers()
    def log_message(self, *args): pass
HTTPServer(('127.0.0.1', port), Handler).serve_forever()
''')
    original = subprocess.Popen
    commands = []
    def launch_process(args, **kwargs):
        commands.append(args)
        return original([sys.executable, str(script), *args[1:]], **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', launch_process)
    tunnel = Tunnel('fake-cloudflared', 'synthetic-tunnel-secret')
    tunnel.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and tunnel.status != 'Online':
            time.sleep(0.05)
        assert tunnel.status == 'Online'
        first = tunnel.process
        first.kill()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and len(commands) < 2:
            time.sleep(0.05)
        assert len(commands) >= 2
        assert all('synthetic-tunnel-secret' not in ' '.join(args) for args in commands)
    finally:
        tunnel.stop()
    assert tunnel.status == 'Offline' and tunnel.process is None


@responses.activate
def test_tunnel_checksum_failure_never_creates_executable(tmp_path, monkeypatch):
    import platform

    from copydesk import tunnel

    monkeypatch.setitem(tunnel.PINS, (platform.system(), platform.machine()), ('synthetic-archive', '0' * 64))
    responses.get(f'https://github.com/cloudflare/cloudflared/releases/download/{tunnel.VERSION}/synthetic-archive', body=b'untrusted')
    with pytest.raises(domains.DomainProblem, match='checksum'):
        tunnel.binary(tmp_path)
    assert not any(path.name in {'cloudflared', 'cloudflared.exe'} and path.is_file() for path in tmp_path.rglob('*'))


def test_authoritative_dns_queries_every_nameserver_and_requires_agreement(monkeypatch):
    from types import SimpleNamespace

    import dns.flags
    import dns.message
    import dns.name
    import dns.rrset

    class Resolver:
        def resolve(self, name, kind):
            if kind == 'NS':
                return [SimpleNamespace(target='ns1.example.test.'), SimpleNamespace(target='ns2.example.test.')]
            return ['192.0.2.1' if str(name).startswith('ns1') else '192.0.2.2'] if kind == 'A' else []
    resolver = Resolver()
    monkeypatch.setattr(domains, '_resolver', lambda: resolver)
    monkeypatch.setattr(domains.dns.resolver, 'zone_for_name', lambda *_a, **_k: dns.name.from_text('example.test'))
    queries = []
    def query(message, address, timeout):
        queries.append(address)
        response = dns.message.make_response(message)
        response.flags |= dns.flags.AA
        response.answer.append(dns.rrset.from_text('news.example.test.', 300, 'IN', 'A', '192.0.2.10'))
        return response
    monkeypatch.setattr(domains.dns.query, 'udp', query)
    assert domains.authoritative_values('news.example.test', 'A') == ['192.0.2.10']
    assert queries == ['192.0.2.1', '192.0.2.2']


def test_public_reachability_refuses_private_dns_addresses(app, monkeypatch):
    monkeypatch.setattr(domains.socket, 'getaddrinfo', lambda *_a, **_k: [(2, 1, 6, '', ('127.0.0.1', 443))])
    with app.app_context():
        assert not domains.reachable('https://news.example.test')


def test_edge_snapshot_contains_no_editor_session_or_remote_stylesheet_fetch(app, monkeypatch):
    with app.app_context():
        cloudflare.save({'token': 'synthetic', 'account': 'account', 'namespace': 'namespace', 'hostname': 'news.example.test'})
        settings.set_value('hosting.edge', True)
        db.session.commit()
        writes = []
        monkeypatch.setattr(cloudflare.Client, 'call', lambda self, method, path, **kw: writes.append((method, path, kw)))
        edge.snapshot({})
        html = writes[0][2]['data'].decode()
        assert 'Launching soon' in html
        assert 'editor@example.edu' not in html and 'Test Editor' not in html
        assert 'name="csrf_token"' not in html
        assert 'href="/login' not in html and 'href="/join' not in html
        assert writes[0][0] == 'PUT' and writes[0][1].endswith('/values/snapshot')


def test_edge_replay_commits_before_kv_delete_and_retry_is_harmless(app, monkeypatch):
    with app.app_context():
        cloudflare.save({'token': 'synthetic', 'account': 'account', 'namespace': 'namespace', 'hostname': 'news.example.test'})
        settings.set_value('hosting.edge', True)
        subscriber = Subscriber(email='edge-synthetic@example.test', status='active', token='synthetic-edge-token')
        db.session.add(subscriber)
        db.session.commit()
        entry = {'action': 'unsubscribe', 'token': subscriber.token, 'received': utcnow().isoformat() + 'Z'}
        failures = [True]
        def api(self, method, path, **kw):
            if path.endswith('/keys'):
                return [{'name': 'action:replay-test'}]
            if method == 'GET':
                return json.dumps(entry).encode()
            assert db.session.get(EdgeReceipt, 'action:replay-test')
            if failures.pop() if failures else False:
                raise domains.DomainProblem('Synthetic delete failure')
        monkeypatch.setattr(cloudflare.Client, 'call', api)
        with pytest.raises(domains.DomainProblem):
            edge.replay({})
        db.session.rollback()
        assert db.session.get(Subscriber, subscriber.id).status == 'unsubscribed'
        edge.replay({})
        db.session.commit()
        assert len(db.session.scalars(select(EdgeReceipt)).all()) == 1


def test_edge_enable_refuses_unconfirmed_fail_open_and_removes_route(app, monkeypatch):
    with app.app_context():
        cloudflare.save({'token': 'synthetic', 'account': 'account', 'zone': 'zone', 'tunnel': 'tunnel',
                         'hostname': 'news.example.test', 'namespace': 'namespace'})
        db.session.commit()
        app.extensions['copydesk_desktop'] = object()
        calls = []
        def api(self, method, path, **kw):
            calls.append((method, path, kw))
            if path.endswith('/workers/routes'):
                return [] if method == 'GET' else {'id': 'route'}
            return {}
        monkeypatch.setattr(cloudflare.Client, 'call', api)
        try:
            with pytest.raises(domains.DomainProblem, match='fail-open'):
                edge.enable({})
            assert ('DELETE', '/zones/zone/workers/routes/route', {}) in calls
            assert not settings.get('hosting.edge')
        finally:
            app.extensions.pop('copydesk_desktop')


def test_keep_awake_is_opt_in_and_released_when_public_address_is_removed(tmp_path, monkeypatch):
    from copydesk import tunnel

    class Guard:
        started = stopped = 0
        problem = ''
        def start(self):
            Guard.started += 1
        def stop(self):
            Guard.stopped += 1
    monkeypatch.setattr(tunnel, 'AwakeGuard', Guard)
    runtime = DesktopRuntime(tmp_path / 'awake-publication')
    runtime.start(with_worker=False)
    try:
        assert runtime.awake is None
        with runtime.app.app_context():
            settings.set_value('hosting.keep_awake', True)
            db.session.commit()
        runtime.set_public_url('https://news.example.test')
        assert Guard.started == 1
        runtime.apply_keep_awake()
        assert Guard.started == 1
        runtime.set_public_url('')
        assert Guard.stopped == 1 and runtime.awake is None
    finally:
        runtime.stop()


def test_windows_sleep_inhibition_is_cleared_on_the_owning_thread(monkeypatch):
    import ctypes
    import threading
    import time
    from types import SimpleNamespace

    from copydesk import tunnel

    calls = []
    def execution_state(flags):
        calls.append((threading.get_ident(), flags))
        return 1
    monkeypatch.setattr(tunnel.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(kernel32=SimpleNamespace(SetThreadExecutionState=execution_state)), raising=False)
    guard = tunnel.AwakeGuard()
    guard.start()
    deadline = time.monotonic() + 2
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    guard.stop()
    assert [flag for _, flag in calls] == [0x80000001, 0x80000000]
    assert calls[0][0] == calls[1][0] != threading.get_ident()


@pytest.mark.parametrize('source', ['"v=spf1 include:sender.example.test -all"', '"v=spf1 " "include:sender.example.test -all"'])
def test_cloudflare_txt_quoting_preserves_logical_value(source):
    assert cloudflare.record_value({'type': 'TXT', 'content': source}) == 'v=spf1 include:sender.example.test -all'


def test_launch_gate_preserves_server_path_prefix(app, client, editor_client):
    from copydesk.app import PrefixMiddleware

    app.wsgi_app = PrefixMiddleware(app.wsgi_app, '/journal')
    soon(app)
    anonymous = app.test_client()
    assert anonymous.get('/journal/search').location == '/journal/'
    assert anonymous.get('/journal/feed.xml').status_code == 404
    assert anonymous.get('/journal/login').status_code == 200
    assert anonymous.get('/journal/subscribe/thanks').status_code == 200
    assert b'Launching soon' in anonymous.get('/journal/').data
    assert b'Readers see the launching-soon page.' in editor_client.get('/journal/').data


def test_cloudflare_visitor_header_is_trusted_only_on_the_public_listener():
    from copydesk.desktop import LocalRequests

    def app(environ, start):
        return Response(environ['REMOTE_ADDR'])(environ, start)
    private = WSGIClient(LocalRequests(app, 'http://127.0.0.1:5080'), Response)
    assert private.get('/', base_url='http://127.0.0.1:5080', headers={'CF-Connecting-IP': '198.51.100.5'}, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).text == '127.0.0.1'
    public = WSGIClient(PublicRequests(app, 'https://news.example.test', 'cloudflare'), Response)
    kwargs = {'base_url': 'http://news.example.test', 'environ_overrides': {'REMOTE_ADDR': '127.0.0.1'}}
    assert public.get('/', headers={'X-Forwarded-For': '198.51.100.9'}, **kwargs).status_code == 400
    assert public.get('/', headers={'CF-Connecting-IP': '198.51.100.5', 'X-Forwarded-For': '198.51.100.9'}, **kwargs).text == '198.51.100.5'


def test_cloudflare_sign_in_setup_is_csrf_protected_and_api_token_is_backup(app, editor_client):
    assert editor_client.post('/dashboard/domain', data={'action': 'oauth.setup'}).status_code == 400
    response = editor_client.post('/dashboard/domain', data={'action': 'oauth.setup', 'csrf_token': 'test-csrf',
        'client_id': 'synthetic-public-client', 'relay_url': 'https://relay.example.test/oauth/cloudflare/callback'})
    assert response.status_code == 302
    html = editor_client.get('/dashboard/domain').text
    assert 'Sign in with Cloudflare' in html
    assert 'Use an API token instead (backup)' in html
    with app.app_context():
        from copydesk import hosting_oauth
        assert hosting_oauth.available()
        assert 'argotunnel.write' in hosting_oauth.config()['scopes']
        assert 'offline_access' in hosting_oauth.config()['scopes']


def test_oauth_setup_rejects_an_insecure_relay(editor_client):
    response = editor_client.post('/dashboard/domain', data={'action': 'oauth.setup', 'csrf_token': 'test-csrf',
        'client_id': 'synthetic-public-client', 'relay_url': 'http://relay.example.test/oauth/cloudflare/callback'})
    assert response.status_code == 422


def test_cloudflare_oauth_form_redirect_allowed_only_on_domain_page(editor_client):
    assert "form-action 'self' https://dash.cloudflare.com;" in editor_client.get('/dashboard/domain').headers['Content-Security-Policy']
    assert "https://dash.cloudflare.com" not in editor_client.get('/dashboard/').headers['Content-Security-Policy']
