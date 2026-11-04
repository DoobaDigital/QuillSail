"""Opt-in edge fallback and transactional replay of offline subscriber actions."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from flask import current_app
from sqlalchemy import select

from copydesk import audit, cloudflare, domains, jobs, settings, subscribers
from copydesk.db import db
from copydesk.models import EdgeReceipt, Job, Subscriber
from copydesk.utils import is_valid_email, utcnow


def queue_path(data):
    return '/accounts/' + data['account'] + '/storage/kv/namespaces/' + data['namespace']


@jobs.handler('edge.enable')
def enable(payload):
    row, data = cloudflare.connection()
    if row.status in {'disconnecting', 'authorization_required'}:
        return
    if not current_app.extensions.get('copydesk_desktop'):
        raise domains.DomainProblem('The offline fallback is for desktop publications.')
    if not data.get('tunnel'):
        raise domains.DomainProblem('Connect a Cloudflare domain before enabling the fallback.')
    client = cloudflare.Client(data)
    account = '/accounts/' + data['account']
    name = 'quillsail-' + domains.instance_id()
    if not data.get('namespace'):
        namespaces = client.pages(account + '/storage/kv/namespaces')
        namespace = next((v for v in namespaces if v['title'] == name), None)
        if namespace is None:
            namespace = client.call('POST', account + '/storage/kv/namespaces', json={'title': name})
        data['namespace'] = namespace['id']
        cloudflare.save(data)
        db.session.commit()
    metadata = {'main_module': 'fallback.js', 'compatibility_date': '2026-10-01', 'bindings': [
        {'type': 'kv_namespace', 'name': 'QUEUE', 'namespace_id': data['namespace']},
        {'type': 'plain_text', 'name': 'HOST', 'text': data['hostname']},
        {'type': 'ratelimit', 'name': 'LIMITER', 'namespace_id': str(int(domains.instance_id()[:8], 16)),
         'simple': {'limit': 10, 'period': 60}}]}
    source = (Path(__file__).parent / 'edge/fallback.js').read_bytes()
    client.call('PUT', account + '/workers/scripts/' + name, files={
        'metadata': (None, json.dumps(metadata), 'application/json'),
        'fallback.js': ('fallback.js', source, 'application/javascript+module')})
    data['worker'] = name
    cloudflare.save(data)
    db.session.commit()
    # Never replace a route owned by another application.
    routes_path = '/zones/' + data['zone'] + '/workers/routes'
    routes = client.call('GET', routes_path)
    pattern = data['hostname'] + '/*'
    matching = [r for r in routes if r['pattern'] == pattern]
    if matching and any(r.get('script') != name for r in matching):
        raise domains.DomainProblem('Another Worker uses this hostname. No route was replaced.')
    route = matching[0] if matching else client.call('POST', routes_path, json={
        'pattern': pattern, 'script': name, 'request_limit_fail_open': True})
    # Explicitly preserve fail-open behavior, even on retries.
    client.call('PUT', routes_path + '/' + route['id'], json={
        'pattern': pattern, 'script': name, 'request_limit_fail_open': True})
    verified = client.call('GET', routes_path + '/' + route['id'])
    if verified.get('request_limit_fail_open') is not True:
        client.call('DELETE', routes_path + '/' + route['id'])
        raise domains.DomainProblem('Cloudflare did not confirm fail-open behavior. The fallback route was removed; hosting remains connected.')
    data['route'] = route['id']
    cloudflare.save(data)
    settings.set_value('hosting.edge', True)
    jobs.enqueue('edge.snapshot')
    audit.record('edge.enabled', label=data['hostname'])


def snapshot_fingerprint():
    values = {key: settings.get(key) for key in settings.REGISTRY
              if key.startswith(('site.', 'launch.', 'appearance.'))}
    values['public_url'] = current_app.extensions['copydesk'].config.base_url
    from copydesk.launch import signup_available

    values['signup_available'] = signup_available()
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def schedule_snapshot():
    if settings.get('hosting.edge') and settings.get('hosting.edge_snapshot') != snapshot_fingerprint():
        pending = db.session.scalar(select(Job.id).where(Job.kind == 'edge.snapshot', Job.status.in_(('queued', 'running'))).limit(1))
        if pending is None:
            jobs.enqueue('edge.snapshot')


@jobs.handler('edge.snapshot')
def snapshot(payload):
    if not settings.get('hosting.edge'):
        return
    _, data = cloudflare.connection()
    # An anonymous, launching-only rendering can never include editor data.
    from flask import render_template
    from premailer import Premailer

    from copydesk import auth, launch

    with current_app.test_request_context('/', base_url='https://' + data['hostname'],
                                          environ_overrides={'quillsail.listener': 'public'}):
        auth.load_user()
        html = render_template('public/launching.html', groups=[], signup_available=launch.signup_available())
    # Read package CSS, never fetch stylesheets or uploads from a remote URL.
    sheets = ''.join((Path(__file__).parent / 'static/css' / name).read_text()
                     for name in ('copydesk.css', 'publication.css'))
    for theme in reversed(current_app.extensions['copydesk'].theme_chain()):
        for filename in theme.stylesheets:
            path = (theme.static_dir / filename).resolve()
            if not path.is_relative_to(theme.static_dir.resolve()) or not path.is_file():
                raise domains.DomainProblem('The theme stylesheet cannot be included in the offline snapshot.')
            sheets += path.read_text(encoding='utf-8')
    sheets += settings.get('appearance.custom_css', '')
    html = Premailer(html, css_text=sheets, allow_network=False, remove_classes=False,
                     disable_validation=True).transform()
    if len(html.encode()) > 512 * 1024:
        raise domains.DomainProblem('The launch page is too large for the offline snapshot.')
    cloudflare.Client(data).call('PUT', queue_path(data) + '/values/snapshot', data=html.encode(), raw=True)
    settings.set_value('hosting.edge_snapshot', snapshot_fingerprint())


def replay_entry(key, entry):
    """Stage receipt and subscriber changes together; caller commits before KV delete."""
    if db.session.get(EdgeReceipt, key):
        return
    try:
        received = datetime.fromisoformat(entry['received'].replace('Z', '+00:00')).astimezone(UTC).replace(tzinfo=None)
        if received > utcnow() + timedelta(minutes=5):
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        received = utcnow()
        entry = {}
    db.session.add(EdgeReceipt(id=key, received_at=received))
    if entry.get('action') == 'unsubscribe':
        subscriber = db.session.scalar(select(Subscriber).where(Subscriber.token == entry.get('token', '')))
        if subscriber:
            subscribers.unsubscribe(subscriber)
            subscriber.unsubscribed_at = min(subscriber.unsubscribed_at or received, received)
    elif entry.get('action') == 'subscribe' and isinstance(entry.get('email'), str) and len(entry['email']) <= 254 and is_valid_email(entry['email']):
        subscribers.subscribe(entry['email'], name=str(entry.get('name', ''))[:100], source='offline')
    audit.record('edge.replayed', label='Offline subscriber request')


@jobs.handler('edge.replay')
def replay(payload):
    if not settings.get('hosting.edge'):
        return
    _, data = cloudflare.connection()
    client = cloudflare.Client(data)
    path = queue_path(data)
    # Bound work per maintenance cycle. Keys not returned remain for the next pass.
    keys = client.call('GET', path + '/keys', params={'prefix': 'action:', 'limit': 100})
    oldest = None
    for item in keys:
        key = item['name']
        if not key.startswith('action:') or len(key) > 80:
            continue
        value_path = path + '/values/' + quote(key, safe='')
        raw = client.call('GET', value_path, raw=True)
        try:
            entry = json.loads(raw) if len(raw) <= 4096 else {}
            if not isinstance(entry, dict):
                entry = {}
        except (ValueError, TypeError):
            entry = {}
        replay_entry(key, entry)
        receipt = db.session.get(EdgeReceipt, key)
        if entry.get('action') == 'unsubscribe':
            oldest = min(oldest or receipt.received_at, receipt.received_at)
        db.session.commit()
        client.call('DELETE', value_path)
    settings.set_value('hosting.edge_warning', bool(oldest and oldest < utcnow() - timedelta(days=3)))
    settings.set_value('hosting.edge_last_replay', utcnow().isoformat())


@jobs.handler('edge.disable')
def disable(payload):
    _, data = cloudflare.connection()
    if not data.get('worker'):
        return
    client = cloudflare.Client(data)
    if data.get('route'):
        routes = client.call('GET', '/zones/' + data['zone'] + '/workers/routes')
        route = next((r for r in routes if r['id'] == data['route']), None)
        if route and route.get('script') != data['worker']:
            raise domains.DomainProblem('The fallback route changed elsewhere. Review it before disconnecting.')
        client.call('DELETE', '/zones/' + data['zone'] + '/workers/routes/' + data['route'])
        data.pop('route', None)
        data['edge_stopped_at'] = utcnow().isoformat()
        cloudflare.save(data)
        db.session.commit()
    stopped = datetime.fromisoformat(data.get('edge_stopped_at', utcnow().isoformat()))
    if stopped > utcnow() - timedelta(minutes=5):
        raise jobs.RetryLater('The fallback route is removed; waiting for queued writes to settle.', delay=60)
    replay({})
    if data.get('namespace'):
        keys = client.call('GET', queue_path(data) + '/keys', params={'prefix': 'action:', 'limit': 1})
        if keys:
            raise jobs.RetryLater('Subscriber requests remain; retrying after replay.', delay=60)
    client.call('DELETE', '/accounts/' + data['account'] + '/workers/scripts/' + data['worker'])
    if data.get('namespace'):
        client.call('DELETE', queue_path(data))
    for key in ('worker', 'route', 'namespace', 'edge_stopped_at'):
        data.pop(key, None)
    cloudflare.save(data)
    settings.set_value('hosting.edge', False)
    audit.record('edge.disabled', label=data['hostname'])
