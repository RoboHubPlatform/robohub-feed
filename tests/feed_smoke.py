#!/usr/bin/env python3
"""Feed's smoke test, end to end, beside stand-ins for what it reads from.

Builds Feed and runs it as the keeper would — a workspace, a client id and
secret, the issuer's address and each called application's — beside stand-ins
on loopback for the keeper's token issuer (/auth/service-token), Mesh (its
/mesh/api projects, sources and values) and Aquarium's appapi (/api/v1/values),
with Energy given an address nothing answers at and a `gateway` that the
manifest does not call. Then it does what a person does, through the forms:

- grants and form tokens: feed:read looks and cannot change, a ticket without a
  feed grant sees nothing, a post without the form token changes nothing;
- a feed made (its id 24 hex characters), one with a 29 s interval refused;
- items picked from what the stand-ins list (Energy reported as not answering),
  an item from an application the manifest does not call refused, and that
  application never asked;
- publish now: every reading asked for with a token for its own audience and a
  read-only scope; the directory publisher's files in place — the snapshot,
  widget.js, example.html, no temporary file left — and every snapshot held to
  schemas/feed.v1.json and searched for the stand-ins' ids, addresses and
  tokens;
- the refresh loop publishing a new value by itself;
- a Mesh source that stops answering: its last value kept, marked stale, and the
  snapshot still written; an appapi value older than five minutes stale;
- a publisher that cannot write recorded with its reason and tried again at the
  next refresh, kinds that do not exist yet and refused folders not saved;
- a disabled feed not published; the preview; a deleted feed's snapshot removed
  from its directory publishers.

Usage: feed_smoke.py
"""

import html
import http.server
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROJECTS = ROOT.parent
RHO = str(PROJECTS / "rho" / "bin" / "rho") if (PROJECTS / "rho" / "bin" / "rho").exists() else "rho"
sys.path.insert(0, str(HERE))
import snapshot_check  # noqa: E402

# What the stand-ins hold: ids, names and addresses that must never reach a
# snapshot. The ids are unlike any word a snapshot uses.
PROJECT = "Greenhouse-7"
SOURCE = "ba06f37ca34ba32c.temperature"
PUMP = "pump.state"
WATER = "water.temperature"
GATEWAY_SECRET = "gw-secret-address-9f3a"
CLIENT_SECRET = "feed-client-secret-" + secrets.token_hex(8)

failures = []
snapshots_seen = []


def check(ok: bool, what: str) -> None:
    print(("[PASS] " if ok else "[FAIL] ") + what)
    if not ok:
        failures.append(what)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Stand:
    """What the stand-ins were asked and what they answer."""
    issued = []          # each token request: client_id, audience, scopes, token
    tokens = {}          # token -> (audience, scopes)
    asked = []           # each request: server, method, path, token
    mesh_value = "21.537"
    mesh_down = False
    pump_age = 20
    lock = threading.Lock()


def make_handler(server_name: str):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status: int, body, content_type: str = "application/json") -> None:
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _token(self):
            header = self.headers.get("Authorization", "")
            token = header[7:] if header.startswith("Bearer ") else ""
            with Stand.lock:
                Stand.asked.append({"server": server_name, "method": self.command, "path": self.path, "token": token})
                return Stand.tokens.get(token)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode() if length else ""
            if server_name == "issuer" and self.path == "/auth/service-token":
                form = dict(urllib.parse.parse_qsl(body))
                if form.get("client_id") != "feed" or form.get("client_secret") != CLIENT_SECRET:
                    self._send(401, {"error": "invalid client"})
                    return
                token = f"stand-token-{form.get('audience')}-{secrets.token_hex(6)}"
                with Stand.lock:
                    Stand.issued.append(dict(form, token=token))
                    Stand.tokens[token] = (form.get("audience", ""), form.get("scopes", ""))
                self._send(200, {"token": token, "expires_in": 300})
                return
            self._token()
            self._send(405, {"error": "read only"})

        def do_GET(self):
            granted = self._token()
            if server_name == "gateway":
                self._send(200, "never to be asked", "text/plain")
                return
            if server_name in ("mesh", "aquarium") and (granted is None or granted[0] != server_name):
                self._send(401, {"error": "authentication required"})
                return
            path = urllib.parse.unquote(self.path.split("?", 1)[0])
            if server_name == "mesh":
                self.mesh(path)
            elif server_name == "aquarium":
                self.aquarium(path)
            else:
                self._send(404, {"error": "no such path"})

        def mesh(self, path: str) -> None:
            if path == "/mesh/api/projects":
                self._send(200, [{"id": PROJECT, "name": "Greenhouse", "active": True,
                                  "gateway_url": f"http://127.0.0.1:9/{GATEWAY_SECRET}"}])
            elif path == f"/mesh/api/projects/{PROJECT}/sources":
                self._send(200, [
                    {"id": SOURCE, "name": "Bench node · Temperature", "owner": "Bench node", "unit": "°C",
                     "project": PROJECT, "instance": "ba06f37ca34ba32c", "direction": "input",
                     "value_path": f"/mesh/api/projects/{PROJECT}/sources/{SOURCE}/value"},
                    {"id": "ba06f37ca34ba32c.state", "name": "Bench node · Relay", "unit": "", "direction": "output"}])
            elif path == f"/mesh/api/projects/{PROJECT}/sources/{SOURCE}/value":
                if Stand.mesh_down:
                    self._send(503, {"error": "gateway down"})
                else:
                    self._send(200, Stand.mesh_value, "text/plain; charset=utf-8")
            else:
                self._send(200, "", "text/plain")

        def aquarium(self, path: str) -> None:
            now = int(time.time())
            values = {
                PUMP: {"id": PUMP, "value": "on", "unit": "", "label": "Return pump", "kind": "export",
                       "updated_at": now - Stand.pump_age},
                WATER: {"id": WATER, "value": "25.24", "unit": "°C", "label": "Water temperature", "kind": "derived",
                        "updated_at": now - 5},
            }
            if path == "/api/v1/values":
                self._send(200, {"application": "aquarium", "values": list(values.values())})
            elif path.startswith("/api/v1/values/") and path.endswith("/history"):
                points = [{"t": (now - 3600 * k) * 1000, "v": 25 + k / 10} for k in range(20, -1, -1)]
                self._send(200, {"ok": True, "points": points})
            elif path.startswith("/api/v1/values/") and path[len("/api/v1/values/"):] in values:
                self._send(200, values[path[len("/api/v1/values/"):]])
            else:
                self._send(404, {"error": "no such value"})

    return Handler


def serve(name: str):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", free_port()), make_handler(name))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, base: str, token: str):
        self.base = base
        self.token = token
        self.csrf = ""

    def request(self, method: str, path: str, fields: dict = None):
        """(status, body, location), following no redirect."""
        data = urllib.parse.urlencode(fields).encode() if fields is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(req, timeout=60) as response:
                return response.status, response.read().decode("utf-8", "replace"), response.headers.get("Location", "")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace"), error.headers.get("Location", "")

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, fields: dict, token: bool = True):
        fields = dict(fields)
        if token:
            fields["csrf"] = self.csrf
        return self.request("POST", path, fields)


def mint(home: str, scopes: str, subject: str = "smoke") -> str:
    keys = os.path.join(home, ".rho", "auth")
    result = subprocess.run([RHO, "auth", "ticket", "--private", os.path.join(keys, "private.pem"), "--issuer", "keeper",
                             "--audience", "feed", "--subject", subject, "--scopes", scopes, "--ttl", "1h"],
                            check=True, capture_output=True, text=True)
    return result.stdout.strip()


def wait_until(what: str, probe, seconds: float = 45):
    deadline = time.time() + seconds
    last = None
    while time.time() < deadline:
        last = probe()
        if last:
            return last
        time.sleep(0.5)
    raise AssertionError(f"{what} did not happen in {seconds:.0f} s (last: {last!r})")


def read_snapshot(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    snapshots_seen.append(text)
    return json.loads(text)


def state_status(workspace: str, feed_id: str) -> list:
    try:
        text = Path(workspace, "state", feed_id + ".txt").read_text()
    except OSError:
        return []
    for line in text.splitlines():
        if line.startswith("status|"):
            parts = line.split("|")
            return [parts[1], parts[2], urllib.parse.unquote(parts[3]), parts[4]]
    return []


def main() -> int:
    build = subprocess.run([RHO, "build", str(ROOT)], capture_output=True, text=True,
                           env=dict(os.environ, ROBOHUB_WORKSPACE=os.environ.get("ROBOHUB_WORKSPACE", str(PROJECTS))))
    if build.returncode != 0:
        raise SystemExit("build failed:\n" + build.stdout + build.stderr)
    issuer, issuer_url = serve("issuer")
    mesh, mesh_url = serve("mesh")
    aquarium, aquarium_url = serve("aquarium")
    gateway, gateway_url = serve("gateway")
    energy_url = f"http://127.0.0.1:{free_port()}"
    root = tempfile.mkdtemp(prefix="feed-smoke-")
    workspace = os.path.join(root, "workspace")
    home = os.path.join(root, "home")
    os.makedirs(workspace)
    os.makedirs(os.path.join(home, ".rho", "auth"))
    subprocess.run([RHO, "auth", "keygen", "--dir", os.path.join(home, ".rho", "auth"), "--force"],
                   check=True, capture_output=True, text=True)
    secret_file = os.path.join(root, "client.secret")
    Path(secret_file).write_text(CLIENT_SECRET + "\n")
    os.chmod(secret_file, 0o600)
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    for name in list(env):
        if name.startswith("RHO_SERVICE_") or name.startswith("ROBOHUB_BUS"):
            env.pop(name)
    env.update({
        "HOME": home, "RHO_APP_WORKSPACE": workspace, "ROBOHUB_APP_WORKSPACE": workspace,
        "RHO_HTTP_ADDR": f"127.0.0.1:{port}", "RHO_CLIENT_ID": "feed", "RHO_CLIENT_SECRET_FILE": secret_file,
        "RHO_AUTH_URL": issuer_url, "RHO_SERVICE_MESH_URL": mesh_url, "RHO_SERVICE_AQUARIUM_URL": aquarium_url + "/",
        "RHO_SERVICE_ENERGY_URL": energy_url, "RHO_SERVICE_GATEWAY_URL": gateway_url,
    })
    env.pop("RHO_AUTH_STANDALONE", None)
    log_path = os.path.join(root, "feed.log")
    log = open(log_path, "w")
    process = subprocess.Popen([str(ROOT / "build" / "feed")], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    forbidden = [PROJECT, "ba06f37ca34ba32c", PUMP, WATER, "mesh", "aquarium", "energy", "gateway", GATEWAY_SECRET,
                 mesh_url, aquarium_url, issuer_url, energy_url, gateway_url, "127.0.0.1", "Bearer", "stand-token",
                 CLIENT_SECRET, workspace, home]
    try:
        admin = Client(base, mint(home, "feed:*"))
        wait_until("feed answering", lambda: admin.get("/healthz")[0] == 200, 60)
        public = Path(workspace, "public")

        # @verifies FEED-0007
        status, page, _ = admin.get("/feeds/new")
        found = re.search(r'name="csrf" value="([^"]*)"', page)
        check(status == 200 and found is not None, "the new-feed page draws a form token")
        admin.csrf = html.unescape(found.group(1)) if found else ""
        check('class="rh-top"' in page and "/ui/robohub.css" in page, "the page has the RoboHub shell and look")
        reader = Client(base, mint(home, "feed:read", "reader"))
        reader.csrf = admin.csrf
        stranger = Client(base, mint(home, "mesh:*", "stranger"))
        check(reader.get("/")[0] == 200, "feed:read looks at the feeds")
        status, _, _ = reader.post("/feeds", {"title": "Nope", "interval": "60", "enabled": "1", "pub_local": "1"})
        check(status == 403, f"feed:read cannot make a feed ({status})")
        check(stranger.get("/")[0] == 403, "a ticket without a feed grant sees nothing")
        check(Client(base, "").get("/")[0] in (302, 303, 307, 401), "no ticket is sent to sign in")
        status, _, _ = admin.post("/feeds", {"title": "Forged", "interval": "60", "enabled": "1", "pub_local": "1"}, token=False)
        check(status == 403, f"a post without the form token is refused ({status})")
        status, _, _ = admin.post("/feeds", {"title": "Forged", "interval": "60", "pub_local": "1", "csrf": "x" * 20}, token=False)
        check(status == 403, "a post with a wrong form token is refused")
        check("Forged" not in Path(workspace, "feeds.txt").read_text() and "Nope" not in Path(workspace, "feeds.txt").read_text(),
              "and nothing was made by them")

        # @verifies FEED-0001
        status, _, location = admin.post("/feeds", {"title": "Garden", "interval": "29", "enabled": "1", "pub_local": "1"})
        check("feed.error.interval" in location, f"a 29 s interval is refused ({location})")
        status, _, location = admin.post("/feeds", {"title": 'Garden "west"', "interval": "30", "enabled": "1", "pub_local": "1"})
        made = re.match(r"^/feeds/([0-9a-f]+)\?done=feed\.created$", location)
        check(status in (302, 303) and made is not None, f"a feed is made and the page goes to it ({status} {location})")
        feed_id = made.group(1) if made else ""
        check(re.fullmatch(r"[0-9a-f]{24}", feed_id) is not None, f"its id is 24 random hex characters ({feed_id})")
        _, _, other = admin.post("/feeds", {"title": "Other", "interval": "60", "pub_local": "1"})
        other_id = other.split("/")[2].split("?")[0] if other.startswith("/feeds/") else ""
        check(other_id != "" and other_id != feed_id, "a second feed has an id of its own")

        # @verifies FEED-0007, FEED-0002
        status, page, _ = admin.get("/feeds/" + feed_id)
        options = {html.unescape(label): html.unescape(value) for value, label in
                   re.findall(r'<option value="([^"]+)" data-unit="[^"]*">([^<]*)</option>', page)}
        check("Mesh · Greenhouse · Bench node · Temperature" in options, f"the picker lists Mesh's sources ({list(options)[:4]})")
        check("Aquarium · Return pump" in options and "Aquarium · Water temperature" in options, "and Aquarium's values")
        check("Did not answer:" in page and "Energy" in page, "and says Energy did not answer")
        air = options.get("Mesh · Greenhouse · Bench node · Temperature", "")
        pump = options.get("Aquarium · Return pump", "")
        water = options.get("Aquarium · Water temperature", "")
        for fields in ({"source": air, "label": "Air", "unit": "°C", "decimals": "1", "history": "1h"},
                       {"source": pump, "label": "Pump", "unit": "", "decimals": "", "history": "none"},
                       {"source": water, "label": "Water", "unit": "°C", "decimals": "1", "history": "24h"}):
            _, _, location = admin.post(f"/feeds/{feed_id}/items", fields)
            check("done=item.added" in location, f"item {fields['label']} added ({location})")
        asked_gateway = len([a for a in Stand.asked if a["server"] == "gateway"])
        _, _, location = admin.post(f"/feeds/{feed_id}/items", {"source": "gateway|nodes|", "label": "Sneaky", "history": "none"})
        check("item.error.app" in location, "an item from an application the manifest does not call is refused")
        _, _, location = admin.post(f"/feeds/{feed_id}/items", {"source": "mesh|Greenhouse-7|", "label": "Half", "history": "none"})
        check("item.error.source" in location, "a Mesh item without its source is refused")

        # @verifies FEED-0002, FEED-0003, FEED-0006
        _, _, location = admin.post(f"/feeds/{feed_id}/publish", {})
        check("done=feed.published" in location, f"publish now publishes ({location})")
        snapshot_path = public / "feeds" / (feed_id + ".json")
        check(snapshot_path.exists(), "the snapshot is at feeds/<id>.json in the publisher's folder")
        check((public / "widget.js").read_text() == (ROOT / "static" / "widget.js").read_text(), "widget.js beside it")
        check((public / "example.html").exists(), "and example.html")
        check(not [p for p in public.rglob("*") if p.name.startswith(".")], "no temporary file is left")
        snap = read_snapshot(snapshot_path)
        items = {i["key"]: i for i in snap.get("items", [])}
        check(snap.get("format") == "robohub-feed" and snap.get("schema") == 1 and snap.get("id") == feed_id and
              snap.get("title") == 'Garden "west"' and snap.get("refresh") == 30, "the snapshot's head")
        check(list(items) == ["i1", "i2", "i3"], f"its items are keyed by position ({list(items)})")
        check(items.get("i1", {}).get("value") == 21.5 and items["i1"]["unit"] == "°C" and items["i1"]["stale"] is False,
              f"the Mesh reading, to one decimal and current ({items.get('i1')})")
        check(items.get("i2", {}).get("value") == "on" and items["i2"]["stale"] is False, "the word state as a string")
        check(items.get("i3", {}).get("value") == 25.2 and len(items["i3"].get("history", [])) >= 20,
              f"the appapi value with its day of history ({len(items.get('i3', {}).get('history', []))} points)")
        check(len(items.get("i1", {}).get("history", [])) == 1, "Mesh's history is what Feed read itself")
        mesh_tokens = [a for a in Stand.asked if a["server"] == "mesh" and "/value" in a["path"]]
        check(bool(mesh_tokens) and all(Stand.tokens.get(a["token"], ("",))[0] == "mesh" for a in mesh_tokens),
              "Mesh is asked with a token for Mesh's audience")
        value_scopes = {Stand.tokens.get(a["token"], ("", ""))[1] for a in mesh_tokens}
        check(value_scopes == {f"mesh:{PROJECT}:read"}, f"and its project's read-only scope ({value_scopes})")
        aqua = [a for a in Stand.asked if a["server"] == "aquarium"]
        check(bool(aqua) and {Stand.tokens.get(a["token"], ("", ""))[1] for a in aqua} == {"aquarium:read"},
              "Aquarium is asked with aquarium:read")
        scopes = {i.get("scopes", "") for i in Stand.issued}
        check(all(s.endswith(":read") for s in scopes), f"every token asked for is read-only ({sorted(scopes)})")
        audiences = {i.get("audience") for i in Stand.issued}
        check(audiences <= {"mesh", "aquarium", "energy"}, f"and only for applications the manifest calls ({audiences})")
        check(len([a for a in Stand.asked if a["server"] == "gateway"]) == asked_gateway == 0,
              "the application the manifest does not call was never asked")
        check(all(not a["path"].startswith("/mesh/api/projects/" + PROJECT + "/sources/" + SOURCE + "/action")
                  and a["method"] == "GET" for a in Stand.asked if a["server"] in ("mesh", "aquarium")),
              "nothing but reads was sent")

        # @verifies FEED-0003, FEED-0006 — the refresh loop, by itself
        Stand.mesh_value = "22.04"
        first = snap["updated_at"]
        wait_until("the loop's refresh", lambda: read_snapshot(snapshot_path)["updated_at"] != first and
                   read_snapshot(snapshot_path)["items"][0]["value"] == 22.0, 50)
        check(True, "the refresh loop published the new reading at the feed's interval")

        # @verifies FEED-0004
        Stand.mesh_down = True
        Stand.pump_age = 400
        before = read_snapshot(snapshot_path)["updated_at"]
        time.sleep(1.1)
        _, _, location = admin.post(f"/feeds/{feed_id}/publish", {})
        snap = read_snapshot(snapshot_path)
        items = {i["key"]: i for i in snap["items"]}
        check(snap["updated_at"] != before and "done=feed.published" in location,
              "the snapshot is still published when a source cannot be read")
        check(items["i1"]["value"] == 22.0 and items["i1"]["stale"] is True, f"the source's last value is kept, stale ({items['i1']})")
        check(items["i2"]["stale"] is True and items["i2"]["value"] == "on", "a value older than five minutes is stale")
        check(items["i3"]["stale"] is False, "and the current one is not")
        status_line = state_status(workspace, feed_id)
        check(status_line and status_line[3] == "1", f"the feed's status counts the reading not current ({status_line})")
        check("Readings not current" in admin.get("/")[1], "and the list says so")
        Stand.mesh_down = False
        Stand.pump_age = 20

        # @verifies FEED-0006
        _, _, location = admin.post("/publishers", {"name": "pages", "kind": "git", "target": "/srv/www"})
        check("publisher.error.later" in location, "a git publisher is refused until it exists")
        _, _, location = admin.post("/publishers", {"name": "etc", "kind": "directory", "target": "/etc/robohub"})
        check("publisher.error.folder" in location, "a system folder is refused")
        _, _, location = admin.post("/publishers", {"name": "keys", "kind": "directory", "target": home + "/.rho/keeper"})
        check("publisher.error.folder" in location, "the keeper's folder is refused")
        check("pages" not in Path(workspace, "feeds.txt").read_text() and "|etc|" not in Path(workspace, "feeds.txt").read_text(),
              "and none of them was saved")
        blocker = Path(root, "blocked")
        blocker.write_text("a file where the publisher wants a folder")
        broken = str(blocker / "site")
        _, _, location = admin.post("/publishers", {"name": "site", "kind": "directory", "target": broken})
        check("done=publisher.saved" in location, f"a second directory publisher is saved ({location})")
        _, _, location = admin.post(f"/feeds/{feed_id}", {"title": 'Garden "west"', "interval": "30", "enabled": "1",
                                                          "pub_local": "1", "pub_site": "1"})
        check("done=feed.saved" in location, "the feed names both publishers")
        before = read_snapshot(snapshot_path)["updated_at"]
        time.sleep(1.1)
        _, _, location = admin.post(f"/feeds/{feed_id}/publish", {})
        status_line = state_status(workspace, feed_id)
        check("feed.error.publish" in location and status_line and "site:" in status_line[2],
              f"a publisher that cannot write is recorded with its reason ({status_line[2] if status_line else ''})")
        check(read_snapshot(snapshot_path)["updated_at"] != before, "and the other publisher still got the snapshot")
        check("site:" in admin.get("/")[1], "the list shows the error")
        blocker.unlink()
        wait_until("the next refresh to publish to the mended folder",
                   lambda: Path(broken, "feeds", feed_id + ".json").exists(), 50)
        wait_until("the error to clear", lambda: (state_status(workspace, feed_id) or ["", "", "x"])[2] == "", 10)
        check(Path(broken, "widget.js").exists(), "the failed publish was tried again at the next refresh")
        read_snapshot(Path(broken, "feeds", feed_id + ".json"))

        # @verifies FEED-0007
        status, page, _ = admin.get(f"/feeds/{feed_id}/preview")
        check(status == 200 and "<robohub-widget" in page and "data:application/json," in page and 'src="/widget.js"' in page,
              "the preview draws the widget with the snapshot inline")
        status, script, _ = admin.get("/widget.js")
        check(status == 200 and "customElements.define" in script, "and serves the widget it publishes")
        _, _, location = admin.post(f"/feeds/{other_id}/publish", {})
        _, _, location = admin.post(f"/feeds/{other_id}", {"title": "Other", "interval": "60", "pub_local": "1"})
        _, _, location = admin.post(f"/feeds/{other_id}/publish", {})
        check("feed.error.disabled" in location, "a disabled feed is not published")

        # @verifies FEED-0003 — every snapshot written in this run
        for text in snapshots_seen + [p.read_text() for p in public.glob("feeds/*.json")]:
            problems = snapshot_check.check(text, forbidden)
            if problems:
                check(False, "a snapshot holds to the schema and holds nothing internal: " + "; ".join(problems))
                break
        else:
            check(bool(snapshots_seen), f"all {len(snapshots_seen)} snapshots read hold to schemas/feed.v1.json "
                                        "and hold no id, address or token of the stand-ins")

        # The checker is not one that passes anything.
        sample = snapshots_seen[-1]
        check(bool(snapshot_check.check(sample.replace('"key":"i1"', '"key":"i1","source":"x"'))) and
              bool(snapshot_check.check(sample.replace('"refresh":30', '"refresh":"30"'))) and
              bool(snapshot_check.check(sample.replace('"Air"', '"' + PROJECT + '"'), forbidden)),
              "the checker refuses a member the schema has not, a wrong type, and a stand-in's id")

        # @verifies FEED-0007
        _, _, location = admin.post(f"/feeds/{feed_id}/delete", {}, token=False)
        check(snapshot_path.exists(), "a delete without the form token deletes nothing")
        _, _, location = admin.post(f"/feeds/{feed_id}/delete", {})
        check(location.startswith("/?done=feed.deleted"), f"the feed is deleted ({location})")
        check(not snapshot_path.exists() and not Path(broken, "feeds", feed_id + ".json").exists(),
              "its snapshot is removed from both directory publishers")
        check(feed_id not in Path(workspace, "feeds.txt").read_text(), "the feed and its items are gone")
        check(not Path(workspace, "state", feed_id + ".txt").exists(), "with its state")
        check((public / "widget.js").exists(), "widget.js stays for the other feeds")
        time.sleep(6)
        check(not snapshot_path.exists(), "and no refresh publishes the deleted feed again")
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
        for server in (issuer, mesh, aquarium, gateway):
            server.shutdown()
        if failures:
            print("\n--- feed log ---\n" + Path(log_path).read_text()[-4000:])
        shutil.rmtree(root, ignore_errors=True)
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("feed smoke ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
