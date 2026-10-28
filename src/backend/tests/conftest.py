import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="swa-test-"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["DATABASE_PATH"] = str(_TMP / "test.sqlite3")
os.environ["APP_MODE"] = "demo"
os.environ["LLM_PROVIDER"] = "none"
os.environ["ENABLE_EXTERNAL_WRITES"] = "false"
for k in ("OPENAI_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "MICROSOFT_CLIENT_ID"):
    os.environ[k] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

SAMPLES = settings.sample_data_dir / "selected_50.jsonl"
needs_samples = pytest.mark.skipif(not SAMPLES.is_file(), reason="sample data folder not available")


class Api:
    def __init__(self, client: TestClient):
        self.c = client
        r = client.post("/api/session", json={})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def _h(self, extra=None):
        return {"X-CSRF-Token": self.csrf, **(extra or {})}

    def post(self, url, json=None, headers=None, **kw):
        return self.c.post(url, json=json, headers=self._h(headers), **kw)

    def patch(self, url, json=None, headers=None):
        return self.c.patch(url, json=json, headers=self._h(headers))

    def delete(self, url, json=None):
        return self.c.request("DELETE", url, json=json, headers=self._h())


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def api(client):
    return Api(client)


@pytest.fixture(scope="session")
def imported(api):
    if not SAMPLES.is_file():
        pytest.skip("sample data folder not available")
    r = api.post("/api/imports", json={"source": "selected_50", "upload_id": None})
    assert r.status_code == 202, r.text
    job = api.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job
    return job
