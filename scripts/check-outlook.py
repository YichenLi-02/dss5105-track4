"""Check the Outlook (Microsoft Graph) setup, then optionally read from the connected real account.

    src\\backend\\.venv\\Scripts\\python scripts\\check-outlook.py          # .env settings + tenant reachable
    src\\backend\\.venv\\Scripts\\python scripts\\check-outlook.py --live   # also read the connected mailbox

Read-only. Never sends mail, never writes or deletes calendar events, never prints a secret, a token or mail content:
--live reports only the account label, message counts and timestamps, and saves them to
local-data/outlook-check.json (a local file - do not upload it).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/backend"))
from app.config import settings  # noqa: E402
from app.providers import net  # noqa: E402

GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
REPORT = settings.data_dir / "outlook-check.json"
problems: list[str] = []


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def bad(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    problems.append(msg)


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def check_config() -> None:
    print("1. .env settings")
    cid = settings.microsoft_client_id
    if not cid:
        bad("MICROSOFT_CLIENT_ID is empty (Entra app -> Overview -> Application (client) ID)")
    elif not GUID.match(cid):
        bad("MICROSOFT_CLIENT_ID is not a GUID - copy the Application (client) ID, not the object ID or name")
    else:
        ok(f"MICROSOFT_CLIENT_ID looks valid ({cid[:8]}...)")

    tenant = settings.microsoft_tenant_id
    if tenant in ("common", "organizations", "consumers") or GUID.match(tenant):
        ok(f"MICROSOFT_TENANT_ID = {tenant}")
        if tenant == "organizations":
            warn("organizations rejects personal Outlook.com/Hotmail accounts; use common for those")
    else:
        bad("MICROSOFT_TENANT_ID must be common, organizations, consumers or the Directory (tenant) ID GUID")

    secret = settings.microsoft_client_secret
    if not secret:
        warn("MICROSOFT_CLIENT_SECRET is empty - fine only if the redirect URI is under 'Mobile and desktop applications'")
    elif GUID.match(secret):
        bad("MICROSOFT_CLIENT_SECRET looks like the Secret ID (a GUID); paste the secret's Value instead")
    else:
        ok("MICROSOFT_CLIENT_SECRET is set (value not shown)")

    redirect = urlparse(settings.microsoft_redirect_uri)
    if redirect.path != "/api/connections/microsoft/callback":
        bad("MICROSOFT_REDIRECT_URI must end with /api/connections/microsoft/callback")
    elif redirect.scheme == "http" and redirect.hostname not in ("localhost", "127.0.0.1"):
        bad("MICROSOFT_REDIRECT_URI over http must use localhost")
    else:
        ok(f"MICROSOFT_REDIRECT_URI = {settings.microsoft_redirect_uri} (must match Entra exactly)")
        if redirect.hostname == "127.0.0.1":
            warn("the Entra portal rejects http://127.0.0.1 in the text box; use localhost or edit the app manifest")
    if (redirect.port or 80) != (urlparse(settings.app_origin).port or 80):
        warn("redirect URI port differs from APP_ORIGIN; the callback must reach this same server")

    print("2. Tenant reachable")
    try:
        r = net.request("GET", f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration",
                        timeout=15)
        if r.status_code == 200:
            ok("login.microsoftonline.com answered for this tenant")
        else:
            bad(f"tenant lookup returned HTTP {r.status_code} - check MICROSOFT_TENANT_ID")
    except Exception as exc:  # noqa: BLE001
        bad(f"could not reach login.microsoftonline.com ({type(exc).__name__}) - check network/proxy")


def check_live() -> None:
    from app.db import connect, loads
    from app.providers import oauth

    print("3. Connected account (read-only)")
    report: dict = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with connect() as conn:
        row = conn.execute("SELECT * FROM connections WHERE id='conn_microsoft'").fetchone()
        if not row or row["status"] != "connected":
            bad("Outlook is not connected yet - open the app: Sources -> Connections -> Microsoft -> Read mail")
            return
        report["account"] = row["account_label"]
        report["scopes"] = loads(row["scopes_json"], [])
        ok(f"connected as {row['account_label']} with {', '.join(report['scopes'])}")
        try:
            token = oauth.access_token(conn, "microsoft")  # refreshes if needed; never printed
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            bad(f"no usable token ({getattr(exc, 'code', type(exc).__name__)}) - reconnect Outlook in the app")
            return
    auth = {"Authorization": f"Bearer {token}"}

    me = net.request("GET", "https://graph.microsoft.com/v1.0/me", params={"$select": "id"}, headers=auth)
    (ok if me.status_code == 200 else bad)(f"GET /me -> HTTP {me.status_code}")

    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    inbox = net.request("GET", "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages", headers=auth,
                        params={"$top": "10", "$select": "receivedDateTime", "$orderby": "receivedDateTime desc",
                                "$filter": f"receivedDateTime ge {since}"})
    if inbox.status_code == 200:
        dates = [m["receivedDateTime"] for m in inbox.json().get("value", [])]
        report["inbox_last_30_days_first_page"] = len(dates)
        report["newest_received"] = dates[0] if dates else None
        ok(f"inbox readable: {len(dates)} message(s) in the first page of the last 30 days"
           + (f", newest {dates[0]}" if dates else ""))
    else:
        bad(f"inbox list -> HTTP {inbox.status_code} {_graph_code(inbox)}")

    need = oauth.CAPABILITY_SCOPES["microsoft"]["read_busy"]
    if not all(s in report["scopes"] for s in need) and set(report["scopes"]) & oauth.LEGACY_MS_SCOPES:
        warn("calendar was authorised with Calendars.ReadBasic, which Graph rejects (403) for personal accounts - "
             "in the app open Sources -> Connections -> Microsoft and authorise the calendar again "
             f"(asks for {', '.join(need)}, still read-only)")
    elif all(s in report["scopes"] for s in need):
        now = datetime.now(timezone.utc)
        cal = net.request("GET", "https://graph.microsoft.com/v1.0/me/calendarView", headers=auth,
                          params={"startDateTime": now.isoformat(), "endDateTime": (now + timedelta(days=7)).isoformat(),
                                  "$select": "id", "$top": "50"})
        if cal.status_code == 200:
            report["calendar_events_next_7_days"] = len(cal.json().get("value", []))
            ok(f"calendar readable: {report['calendar_events_next_7_days']} event(s) in the next 7 days")
        else:
            bad(f"calendarView -> HTTP {cal.status_code} {_graph_code(cal)}")
    else:
        warn("calendar free/busy permission not granted yet (optional)")

    # The app's own Outlook study calendar (optional): only read here - its id, name and permission to edit.
    from app.providers.writers import app_calendar_id  # noqa: E402
    with connect() as conn:
        study = app_calendar_id(conn, "microsoft")
    if not all(s in report["scopes"] for s in oauth.CAPABILITY_SCOPES["microsoft"]["study_calendar"]):
        warn("Outlook study calendar permission not granted (optional; study blocks can go to Google instead)")
    elif not study:
        warn("Outlook study calendar not created yet - in the app: Connections -> Microsoft -> create study calendar")
    else:
        sc = net.request("GET", f"https://graph.microsoft.com/v1.0/me/calendars/{quote(study, safe='')}", headers=auth,
                         params={"$select": "id,name,canEdit"})
        if sc.status_code == 200:
            info = sc.json()
            report["study_calendar"] = {"name": info.get("name"), "can_edit": info.get("canEdit")}
            (ok if info.get("canEdit") else bad)(f"study calendar found: {info.get('name')!r}, can edit: {info.get('canEdit')}")
        else:
            bad(f"study calendar -> HTTP {sc.status_code} {_graph_code(sc)} (deleted in Outlook? create it again in the app)")

    report["problems"] = problems
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   report saved to {REPORT}")


def _graph_code(r) -> str:
    try:
        return (r.json().get("error") or {}).get("code") or ""
    except Exception:  # noqa: BLE001
        return ""


if __name__ == "__main__":
    print("Outlook setup check")
    check_config()
    if "--live" in sys.argv[1:] and not problems:
        check_live()
    print("\nAll checks passed." if not problems else f"\n{len(problems)} problem(s) - see docs/OUTLOOK_SETUP.md")
    sys.exit(1 if problems else 0)
