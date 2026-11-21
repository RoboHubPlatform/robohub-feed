#!/usr/bin/env python3
"""The http publisher end to end, beside a local receiver (FEED-0008).

Builds Feed and runs it as the keeper would, with a receiver on 127.0.0.1 that
stands in for a site such as a nest module: it records every PUT, answers 401
to a request without the right bearer token, and otherwise 204 — or 500 once,
when asked. Then, through the forms:

- base URLs that are not https (other than the loopback), that carry a user, a
  query or another scheme, and an http publisher without a token, are refused;
- an http publisher is saved with its token: the token is in an owner-only
  file beside the feed file, not in feeds.txt, and the page says only "set";
  saving again with the field empty keeps it;
- publish now sends widget.js, example.html and feeds/<id>.json, each with a
  PUT under the base URL carrying the bearer token, the bodies the files a
  directory publisher writes;
- an answer of 500 is recorded on the feed with its status, and the next
  refresh of the loop tries again and clears it;
- a receiver that is not there is recorded as no answer;
- the token is in no file of the workspace other than its token file, in no
  temporary file left behind, and nowhere in the log.

Usage: http_publisher_smoke.py
"""

import html
import http.server
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from feed_smoke import PROJECTS, RHO, ROOT, Client, check, failures, free_port, mint, state_status, wait_until  # noqa: E402

TOKEN = "nest-" + secrets.token_urlsafe(24)


class Receiver:
    """What the receiver was sent, and how it answers."""
    puts = []            # each PUT: path, authorization, content type, body
    fail_next = 0        # how many PUTs to answer 500
    lock = threading.Lock()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _answer(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_PUT(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        authorization = self.headers.get("Authorization", "")
        with Receiver.lock:
            Receiver.puts.append({"path": self.path, "authorization": authorization,
                                  "type": self.headers.get("Content-Type", ""), "body": body})
            if authorization != "Bearer " + TOKEN:
                self._answer(401)
                return
            if Receiver.fail_next > 0:
                Receiver.fail_next -= 1
                self._answer(500)
                return
        self._answer(204)

    def do_GET(self):
        self._answer(405)


def files_holding(root: str, needle: bytes) -> list:
    found = []
    for path in Path(root).rglob("*"):
        if path.is_file():
            try:
                if needle in path.read_bytes():
                    found.append(path)
            except OSError:
                pass
    return found


def main() -> int:
    build = subprocess.run([RHO, "build", str(ROOT)], capture_output=True, text=True,
                           env=dict(os.environ, ROBOHUB_WORKSPACE=os.environ.get("ROBOHUB_WORKSPACE", str(PROJECTS))))
    if build.returncode != 0:
        raise SystemExit("build failed:\n" + build.stdout + build.stderr)
    receiver = http.server.ThreadingHTTPServer(("127.0.0.1", free_port()), Handler)
    threading.Thread(target=receiver.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{receiver.server_address[1]}/site"
    root = tempfile.mkdtemp(prefix="feed-http-smoke-")
    workspace = os.path.join(root, "workspace")
    home = os.path.join(root, "home")
    os.makedirs(workspace)
    os.makedirs(os.path.join(home, ".rho", "auth"))
    subprocess.run([RHO, "auth", "keygen", "--dir", os.path.join(home, ".rho", "auth"), "--force"],
                   check=True, capture_output=True, text=True)
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {name: value for name, value in os.environ.items()
           if not name.startswith("RHO_SERVICE_") and not name.startswith("ROBOHUB_BUS")}
    env.update({"HOME": home, "RHO_APP_WORKSPACE": workspace, "ROBOHUB_APP_WORKSPACE": workspace,
                "RHO_HTTP_ADDR": f"127.0.0.1:{port}"})
    env.pop("RHO_AUTH_STANDALONE", None)
    log_path = os.path.join(root, "feed.log")
    log = open(log_path, "w")
    process = subprocess.Popen([str(ROOT / "build" / "feed")], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        admin = Client(base, mint(home, "feed:*"))
        wait_until("feed answering", lambda: admin.get("/healthz")[0] == 200, 60)
        status, page, _ = admin.get("/publishers")
        found = re.search(r'name="csrf" value="([^"]*)"', page)
        admin.csrf = html.unescape(found.group(1)) if found else ""
        check(status == 200 and '<option value="http">http</option>' in page and 'name="token"' in page,
              "the publisher form offers kind http, a base URL and a token")

        # @verifies FEED-0008 — what is refused
        for target, why in (("http://example.org/site", "plain http elsewhere"),
                            ("http://127.0.0.1.example.org/site", "a host that only starts like the loopback"),
                            ("https://user:pw@example.org/site", "a user and password"),
                            ("https://example.org/site?x=1", "a query"),
                            ("ftp://example.org/site", "another scheme")):
            _, _, location = admin.post("/publishers", {"name": "bad", "kind": "http", "target": target, "token": TOKEN})
            check("publisher.error.url" in location, f"{why} is refused ({location})")
        _, _, location = admin.post("/publishers", {"name": "bad", "kind": "http", "target": site})
        check("publisher.error.token" in location, "an http publisher without a token is refused")
        _, _, location = admin.post("/publishers", {"name": "bad", "kind": "http", "target": site, "token": "two words"})
        check("publisher.error.token" in location, "and one whose token could start another header")
        check("bad" not in Path(workspace, "feeds.txt").read_text() and not Path(workspace, "publisher-bad.token").exists(),
              "and none of them was saved")

        # @verifies FEED-0008 — the token, kept apart
        _, _, location = admin.post("/publishers", {"name": "nest", "kind": "http", "target": site + "/", "token": TOKEN})
        check("done=publisher.saved" in location, f"an http publisher is saved ({location})")
        token_file = Path(workspace, "publisher-nest.token")
        check(token_file.exists() and token_file.read_text().strip() == TOKEN, "its token is in publisher-nest.token")
        mode = stat.S_IMODE(token_file.stat().st_mode) if token_file.exists() else 0
        check(mode == 0o600, f"readable by its owner only ({oct(mode)})")
        check(TOKEN not in Path(workspace, "feeds.txt").read_text(), "and not in the feed file")
        status, page, _ = admin.get("/publishers")
        check(status == 200 and TOKEN not in page and ">set<" in page, "the page says the token is set and never shows it")
        _, _, location = admin.post("/publishers", {"name": "nest", "kind": "http", "target": site, "token": ""})
        check("done=publisher.saved" in location and token_file.read_text().strip() == TOKEN,
              "saving with the token field empty keeps the token")

        # @verifies FEED-0008 — a publish is every file, with the token
        _, _, location = admin.post("/feeds", {"title": "Settlement", "interval": "30", "enabled": "1", "pub_nest": "1"})
        made = re.match(r"^/feeds/([0-9a-f]+)\?done=feed\.created$", location)
        feed_id = made.group(1) if made else ""
        check(feed_id != "", f"a feed naming the http publisher is made ({location})")
        with Receiver.lock:
            Receiver.puts.clear()
        _, _, location = admin.post(f"/feeds/{feed_id}/publish", {})
        check("done=feed.published" in location, f"publish now publishes to the http publisher ({location})")
        puts = list(Receiver.puts)
        paths = [p["path"] for p in puts]
        check(paths == ["/site/widget.js", "/site/example.html", f"/site/feeds/{feed_id}.json"],
              f"each file is a PUT under the base URL, named as a directory publisher names it ({paths})")
        check(all(p["authorization"] == "Bearer " + TOKEN for p in puts), "every PUT carries the bearer token")
        by_path = {p["path"]: p for p in puts}
        widget = by_path.get("/site/widget.js", {})
        check(widget.get("body") == (ROOT / "static" / "widget.js").read_bytes() and
              widget.get("type", "").startswith("text/javascript"), "widget.js is sent whole, as JavaScript")
        check(by_path.get("/site/example.html", {}).get("body") == (ROOT / "static" / "example.html").read_bytes(),
              "example.html is sent whole")
        snapshot = by_path.get(f"/site/feeds/{feed_id}.json", {})
        try:
            snap = json.loads(snapshot.get("body", b"").decode())
        except ValueError:
            snap = {}
        check(snap.get("format") == "robohub-feed" and snap.get("id") == feed_id and
              snapshot.get("type") == "application/json", "the snapshot is sent as JSON")
        status_line = state_status(workspace, feed_id)
        check(bool(status_line) and status_line[2] == "" and status_line[1] != "0", f"the feed is recorded published ({status_line})")

        # @verifies FEED-0008 — a failure, with its status, then tried again
        with Receiver.lock:
            Receiver.fail_next = 1
            Receiver.puts.clear()
        published = status_line[1] if status_line else ""
        time.sleep(1.1)
        _, _, location = admin.post(f"/feeds/{feed_id}/publish", {})
        status_line = state_status(workspace, feed_id)
        error = status_line[2] if status_line else ""
        check("feed.error.publish" in location and "nest:" in error and "500" in error,
              f"an answer of 500 is recorded with its status ({error})")
        check(status_line and status_line[1] == published, "and the publish is not counted done")
        check(len(Receiver.puts) == 1, f"nothing more is sent after a file that failed ({len(Receiver.puts)})")
        check("HTTP 500" in admin.get("/")[1], "the list shows the error")
        wait_until("the next refresh to try again and clear the error",
                   lambda: (state_status(workspace, feed_id) or ["", "", "x"])[2] == "", 50)
        retried = [p["path"] for p in Receiver.puts]
        check(retried.count(f"/site/feeds/{feed_id}.json") >= 1 and retried.count("/site/widget.js") >= 2,
              f"the loop tried again at the next refresh and every file went ({retried})")

        # @verifies FEED-0008 — no answer at all
        gone = f"http://127.0.0.1:{free_port()}/site"
        _, _, location = admin.post("/publishers", {"name": "gone", "kind": "http", "target": gone, "token": TOKEN})
        _, _, location = admin.post("/feeds", {"title": "Nowhere", "interval": "60", "enabled": "1", "pub_gone": "1"})
        other = re.match(r"^/feeds/([0-9a-f]+)\?", location)
        other_id = other.group(1) if other else ""
        _, _, location = admin.post(f"/feeds/{other_id}/publish", {})
        error = (state_status(workspace, other_id) or ["", "", ""])[2]
        check("feed.error.publish" in location and "gone:" in error and "no answer" in error,
              f"a site that does not answer is recorded as no answer ({error})")

        # @verifies FEED-0008 — the token nowhere else
        holding = [str(p.relative_to(workspace)) for p in files_holding(workspace, TOKEN.encode())]
        check(sorted(holding) == ["publisher-gone.token", "publisher-nest.token"],
              f"the token is in no file of the workspace but the token files ({holding})")
        left = list(Path(workspace, "tmp").glob("*")) if Path(workspace, "tmp").exists() else []
        check(not left, f"no request's body or configuration is left behind ({left})")
        log.flush()
        check(TOKEN not in Path(log_path).read_text(), "and it is nowhere in the log")
        _, _, location = admin.post(f"/feeds/{other_id}/delete", {})
        _, _, location = admin.post("/publishers/gone/delete", {})
        check("done=publisher.removed" in location and not Path(workspace, "publisher-gone.token").exists(),
              "removing a publisher removes its token")
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
        receiver.shutdown()
        if failures:
            print("\n--- feed log ---\n" + Path(log_path).read_text()[-4000:])
        shutil.rmtree(root, ignore_errors=True)
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("http publisher smoke ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
