"""Smoke check against a running server: python scripts/smoke.py [base_url]

Creates a local session, imports the sample set, prints counts. Read-only towards
external services: it never calls Gmail, Calendar, Teams or a model.
"""
import sys
import time

import httpx

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
c = httpx.Client(base_url=base, timeout=20)
print("health:", c.get("/api/health").json())
csrf = c.post("/api/session", json={}).json()["csrf_token"]
h = {"X-CSRF-Token": csrf}
job = c.post("/api/imports", json={"source": "selected_50", "upload_id": None}, headers=h).json()
while job.get("status") in ("queued", "running"):
    time.sleep(0.5)
    job = c.get(f"/api/jobs/{job['id']}").json()
print("import job:", job["status"], job.get("result"))
msgs = c.get("/api/messages").json()
print("inbound:", msgs["total"], "counts:", msgs["counts"])
print("outbound style refs:", c.get("/api/messages?direction=outbound").json()["total"])
tasks = c.get("/api/tasks").json()
print("tasks:", tasks["total"], tasks["counts"])
for t in tasks["items"][:6]:
    print("  ", t["entity_key"], t["status"], t["official_date"], t["official_time"], t["deadline_status"], t["missing_fields"])
