"""Merge model credentials into the local .env without displaying their values."""
import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values, set_key

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
target = root / '.env'
incoming = dotenv_values(args.source)
before = dotenv_values(target)
fields = ('LLM_PROVIDER', 'OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_BASE_URL', 'ALLOW_MODEL_PROCESSING')

if not incoming.get('OPENAI_API_KEY') or not incoming.get('OPENAI_MODEL'):
    raise SystemExit('The supplied file needs a non-empty model key and model name.')
url = urlsplit(incoming.get('OPENAI_BASE_URL') or 'https://api.openai.com/v1')
if (url.scheme != 'https' or url.hostname != 'api.openai.com' or url.port not in (None, 443)
        or url.username or url.password or url.query or url.fragment or url.path.rstrip('/') != '/v1'):
    raise SystemExit('Unexpected model endpoint. No credential was copied or transmitted.')
if before.get('APP_MODE') != 'demo' or before.get('ENABLE_EXTERNAL_WRITES') != 'false':
    raise SystemExit('Expected the existing local demo configuration with external writes disabled.')

for key in fields:
    value = incoming.get(key)
    if value is not None:
        set_key(target, key, value, encoding='utf-8')

after = dotenv_values(target)
assert all(after.get(key) == value for key, value in before.items() if key not in fields)
assert after['OPENAI_API_KEY'] == incoming['OPENAI_API_KEY']
conflicts = [key for key in fields if key in os.environ and os.environ[key] != after.get(key)]
print('Model configuration updated. Secret value not displayed.')
print('Local paths, OAuth credentials, database and external-write settings preserved.')
print('Model:', after.get('OPENAI_MODEL'))
print('Conflicting inherited variable names:', ', '.join(conflicts) if conflicts else 'none')
