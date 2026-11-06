"""Check configured OpenAI model metadata without sending text or generating output."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

import httpx
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
env = dotenv_values(root / '.env')
base = env.get('OPENAI_BASE_URL') or 'https://api.openai.com/v1'
parsed = urlsplit(base)
if (parsed.scheme != 'https' or parsed.hostname != 'api.openai.com'
        or parsed.port not in (None, 443) or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.path.rstrip('/') != '/v1'):
    raise SystemExit('Endpoint is not the expected official OpenAI endpoint. No request made.')
key = env.get('OPENAI_API_KEY')
model = env.get('OPENAI_MODEL')
if not key or not model:
    raise SystemExit('Model key or model name is missing. No request made.')

report = {
    'checked_at': datetime.now(timezone.utc).isoformat(),
    'host': 'api.openai.com',
    'method': 'GET',
    'model': model,
    'model_metadata_access_verified': False,
    'generation_request_sent': False,
    'mail_or_document_content_sent': False,
}
try:
    with httpx.Client(timeout=httpx.Timeout(20, connect=10), trust_env=False, follow_redirects=False) as client:
        response = client.get(base.rstrip('/') + '/models/' + quote(model, safe=''),
                              headers={'Authorization': 'Bearer ' + key})
    report['http_status'] = response.status_code
    payload = response.json()
    if response.status_code == 200 and payload.get('object') == 'model':
        report['model_metadata_access_verified'] = True
    else:
        error = payload.get('error') or {}
        code = error.get('code')
        report['error_code'] = code if isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', code) else 'provider_error'
except (httpx.HTTPError, ValueError) as exc:
    report['transport_or_parse_error'] = type(exc).__name__

out = root / 'local-data/model-access-check.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
