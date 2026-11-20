#!/usr/bin/env python3
"""widget.js under node, with a stand-in DOM (FEED-0005).

The script is run as a page would run it, with just enough of a browser around
it: customElements, HTMLElement with a shadow root whose innerHTML is read back,
fetch answering what the test says, setTimeout recording its delay, and traps on
every way a script could store something, set a cookie or load anything else.
It checks:

- the element is defined as `robohub-widget`, and the snapshot is fetched with
  `credentials: "omit"` (and no referrer);
- table, number and chart (an inline SVG sparkline from the history) draw the
  snapshot's labels, values and units, one item by its key or all of them;
- a stale item is marked as such, and a snapshot that cannot be fetched again
  leaves what was shown with every item marked stale;
- the next fetch is set for the snapshot's own `refresh` interval;
- the style follows the page's scheme (prefers-color-scheme) through CSS custom
  properties;
- labels are escaped, a document that is not a feed snapshot is not drawn, and
  nothing is stored, no cookie set and nothing loaded besides the snapshot.

Usage: widget_test.py
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIDGET = ROOT / "static" / "widget.js"

RUNNER = r"""
const fs = require("fs");
const code = fs.readFileSync(process.argv[1], "utf8");
const results = [];
const check = (ok, what) => results.push({ ok: !!ok, what });
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 10; i++) { await flush(); } };

// What a script could use to keep or send something, each one a trap.
const touched = [];
for (const name of ["localStorage", "sessionStorage", "indexedDB", "caches", "XMLHttpRequest", "WebSocket",
                    "EventSource", "Image", "importScripts"]) {
  Object.defineProperty(global, name, { get() { touched.push(name); return undefined; }, configurable: true });
}
global.navigator = { get sendBeacon() { touched.push("sendBeacon"); return undefined; } };
global.document = {
  get cookie() { touched.push("cookie"); return ""; },
  set cookie(value) { touched.push("cookie=" + value); },
  createElement(name) { touched.push("createElement:" + name); return {}; },
  get head() { touched.push("head"); return {}; },
};

const defined = {};
global.customElements = { get: (name) => defined[name], define: (name, cls) => { defined[name] = cls; } };
class HTMLElement {
  constructor() { this._attrs = {}; this.isConnected = false; }
  getAttribute(name) { return name in this._attrs ? this._attrs[name] : null; }
  setAttribute(name, value) {
    this._attrs[name] = String(value);
    if (this.attributeChangedCallback) { this.attributeChangedCallback(name, null, String(value)); }
  }
  attachShadow(options) { this.shadowRoot = { innerHTML: "", mode: options.mode }; return this.shadowRoot; }
}
global.HTMLElement = HTMLElement;

const fetches = [];
let answer = null;
global.fetch = (url, options) => {
  fetches.push({ url, options });
  return Promise.resolve(answer(url));
};
const ok = (body) => ({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(JSON.stringify(body))) });
const timers = [];
global.setTimeout = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };
global.clearTimeout = () => {};

const snapshot = {
  format: "robohub-feed", schema: 1, id: "0123456789abcdef01234567", title: "Garden", updated_at: "2026-11-20T10:00:00Z",
  refresh: 45,
  items: [
    { key: "i1", label: "Air <img src=x onerror=alert(1)>", value: 21.5, unit: "°C", at: "2026-11-20T09:59:50Z", stale: false,
      history: [["2026-11-20T09:00:00Z", 20.1], ["2026-11-20T09:30:00Z", 20.9], ["2026-11-20T09:59:50Z", 21.5]] },
    { key: "i2", label: "Pump", value: "on", unit: "", at: "2026-11-20T09:40:00Z", stale: true },
  ],
};

(async () => {
  eval(code);
  const Widget = defined["robohub-widget"];
  check(typeof Widget === "function", "the element is defined as robohub-widget");

  const make = (attrs) => {
    const el = new Widget();
    for (const [k, v] of Object.entries(attrs)) { el.setAttribute(k, v); }
    el.isConnected = true;
    el.connectedCallback();
    return el;
  };

  answer = () => ok(snapshot);
  const table = make({ src: "https://example.org/feeds/0123456789abcdef01234567.json", kind: "table" });
  await settle();
  const first = fetches[0] || { options: {} };
  check(first.url === "https://example.org/feeds/0123456789abcdef01234567.json", "the snapshot is fetched from src");
  check(first.options.credentials === "omit", "without credentials");
  check(first.options.referrerPolicy === "no-referrer", "and without a referrer");
  const t = table.shadowRoot.innerHTML;
  check(t.includes("<table") && t.includes("Garden") && t.includes("21.5") && t.includes("°C") && t.includes("Pump"),
        "a table shows every item's label, value and unit");
  check(/<tr class="stale"><td>Pump<span class="flag"[^>]*>stale<\/span>/.test(t), "a stale item is marked stale");
  check(!/<tr class="stale"><td>Air/.test(t), "a current one is not");
  check(!t.includes("<img") && t.includes("&lt;img src=x"), "a label is escaped, never markup");
  check(timers.length === 1 && timers[0].ms === 45000, "the next fetch is set for the snapshot's refresh (45 s)");
  check(t.includes("prefers-color-scheme:dark") && t.includes("--rw-bg") && t.includes("var(--rw-fg)"),
        "the style follows the page's scheme through custom properties");

  const number = make({ src: "s.json", item: "i2", kind: "number" });
  await settle();
  const n = number.shadowRoot.innerHTML;
  check(n.includes('class="one stale"') && n.includes(">stale<") && n.includes("Pump") && !n.includes("Air"),
        "a number shows one item by its key, marked stale");

  const chart = make({ src: "s.json", item: "i1", kind: "chart" });
  await settle();
  const c = chart.shadowRoot.innerHTML;
  check(/<svg[^>]*><polyline points="0\.00,[0-9.]+ 50\.00,[0-9.]+ 100\.00,[0-9.]+"\/><\/svg>/.test(c),
        "a chart draws the history as an inline SVG sparkline");
  check(!c.includes(">stale<"), "a current item has no stale mark");

  // The next fetch fails: what was shown stays, every item marked stale.
  answer = () => ({ ok: false, status: 503, json: () => Promise.reject(new Error("no")) });
  const pending = timers.length;
  timers[timers.length - 1].fn();
  await settle();
  const again = chart.shadowRoot.innerHTML;
  check(again.includes("21.5") && again.includes('class="one stale"') && again.includes(">stale<"),
        "a snapshot that cannot be fetched again keeps its value, marked stale");
  check(timers.length === pending + 1 && timers[timers.length - 1].ms === 45000, "and is tried again at the interval");

  answer = () => ok({ hello: "world" });
  const wrong = make({ src: "other.json", kind: "table" });
  await settle();
  check(wrong.shadowRoot.innerHTML.includes("unavailable"), "a document that is not a feed snapshot is not drawn");
  check(wrong.shadowRoot.mode === "open", "the widget draws in its own shadow root");

  check(fetches.every((f) => f.options && f.options.credentials === "omit"), "every fetch omits credentials");
  check(touched.length === 0, "nothing stored, no cookie, nothing else loaded (" + touched.join(",") + ")");
  console.log(JSON.stringify(results));
})().catch((error) => { console.log(JSON.stringify([{ ok: false, what: "the runner failed: " + error.stack }])); });
"""

# What the script's text must never hold: a way to keep, send or load anything.
FORBIDDEN = ["localStorage", "sessionStorage", "indexedDB", "document.cookie", "XMLHttpRequest", "sendBeacon",
             "WebSocket", "EventSource", "importScripts", "import(", "createElement(", "<script", "<link", "<img",
             "@import", "url(", "eval(", "new Function"]


def main() -> int:
    failures = []

    def check(ok: bool, what: str) -> None:
        print(("[PASS] " if ok else "[FAIL] ") + what)
        if not ok:
            failures.append(what)

    source = WIDGET.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    held = [word for word in FORBIDDEN if word in code]
    check(not held, f"the script holds no way to store, send or load anything else ({held})")
    check(code.count("fetch(") == 1, "it fetches in one place only")
    check("require(" not in code and "import " not in code, "it has no dependency")

    node = shutil.which("node")
    if not node:
        print("node is not installed: widget.js was checked by its text only")
        return 1 if failures else 0
    ran = subprocess.run([node, "-e", RUNNER, str(WIDGET)], capture_output=True, text=True, timeout=60)
    lines = [line for line in ran.stdout.splitlines() if line.startswith("[")]
    if ran.returncode != 0 or not lines:
        check(False, "the widget ran under node:\n" + ran.stdout + ran.stderr)
    else:
        for result in json.loads(lines[-1]):
            check(result["ok"], result["what"])
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("widget ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
