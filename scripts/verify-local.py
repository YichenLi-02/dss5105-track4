"""Read-only local deployment checks; never contacts external providers."""
import json
import os
from pathlib import Path
import re
import sys

import httpx
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
if base != 'http://127.0.0.1:8000':
    raise SystemExit('This local verification script only targets 127.0.0.1:8000.')
config = dotenv_values(root / '.env')
expected_mode = config.get('APP_MODE') or 'demo'
expected_writes = str(config.get('ENABLE_EXTERNAL_WRITES', 'false')).lower() in {'1', 'true', 'yes', 'on'}

with httpx.Client(base_url=base, timeout=10, trust_env=False) as client:
    response = client.get('/api/health')
    response.raise_for_status()
    health = response.json()
    assert health['status'] == 'ok' and health['mode'] == expected_mode
    assert health['capabilities']['external_writes_env_enabled'] == expected_writes
    assert not health['capabilities']['canvas_lms']

    response = client.get('/')
    response.raise_for_status()
    assert '<div id="root"></div>' in response.text
    assets = sorted(set(re.findall(r'(?:src|href)="(/assets/[^\"]+)"', response.text)))
    assert assets, 'No built frontend assets were found.'
    for asset in assets:
        client.get(asset).raise_for_status()

    assert client.get('/api/tasks').status_code == 401
    session_body = {}
    if health['mode'] == 'live':
        # Keep the local authentication gate: read its startup code only for this
        # loopback session. Never put the code in a report or console output.
        rejected = client.post('/api/session', json={})
        assert rejected.status_code == 401
        code = os.environ.get('SWA_BOOTSTRAP_CODE', '')
        if not code:
            log = root / 'local-data/logs/backend.stdout.log'
            matches = re.findall(rb'one-time local session code: ([0-9a-f]+)', log.read_bytes())
            if not matches:
                raise SystemExit('No live startup code found. Restart using Start-Local.cmd.')
            code = matches[-1].decode('ascii')
        session_body['bootstrap_code'] = code
    session = client.post('/api/session', json=session_body)
    session.raise_for_status()
    assert session.json().get('csrf_token')
    preferences = client.get('/api/preferences')
    preferences.raise_for_status()
    model_status = client.get('/api/model/status')
    model_status.raise_for_status()
    connections = client.get('/api/connections')
    connections.raise_for_status()
    google = next((item for item in connections.json()['items'] if item['provider'] == 'google'), {})
    mail = client.get('/api/messages')
    mail.raise_for_status()
    tasks = client.get('/api/tasks')
    tasks.raise_for_status()
    plan = client.get('/api/plans/latest')
    plan.raise_for_status()
    assert client.post('/api/demo/planning-scenario', json={'effort_minutes': 360}).status_code == 403
    report = {
        'url': base,
        'health': health,
        'frontend_assets_checked': assets,
        'session_and_csrf_checks': 'passed',
        'model_status': model_status.json(),
        'user_model_processing_enabled': preferences.json()['allow_model_processing'],
        'user_external_writes_enabled': preferences.json()['enable_external_writes'],
        'google_connected': google.get('status') == 'connected',
        'google_capabilities': google.get('capabilities', {}),
        'mail_count': mail.json()['total'],
        'task_count': tasks.json()['total'],
        'latest_plan_present': plan.json() is not None,
        'external_services_called': False,
        'notes': ('This check only reads local application endpoints. It does not send mail, create calendars/events, '
                  'or invoke a model. Saved connection capabilities do not prove a successful external write.'),
    }

output = root / 'local-data/deployment-check.json'
output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=True, indent=2))
