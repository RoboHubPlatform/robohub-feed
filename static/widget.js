/*
 * @file widget.js
 * @brief <robohub-widget>: shows the items of a RoboHub feed snapshot on any page.
 *
 * @module feed.widget
 * @project robohub-feed
 * @author Aurel Miron
 * @date 2026-11-20
 *
 * SPDX-License-Identifier: MIT
 *
 * @req FEED-0005
 *
 * One script, no dependency (robohub-feed FEED-0005):
 *
 *   <script src="https://example.org/robohub/widget.js" defer></script>
 *   <robohub-widget src="https://example.org/robohub/feeds/<id>.json"
 *                   item="i1" kind="number"></robohub-widget>
 *
 *   src   the snapshot's address
 *   item  an item's key (i1, i2 …), or none for every item
 *   kind  number, chart (a sparkline of the item's history) or table
 *
 * It fetches the snapshot without credentials, draws it, fetches it again at
 * the snapshot's own `refresh` interval, marks a stale item as such and follows
 * the page's light or dark scheme. It stores nothing, sets no cookie and loads
 * nothing but the snapshot. Its colours are CSS custom properties a page may
 * set on the element: --rw-bg, --rw-fg, --rw-muted, --rw-line, --rw-accent,
 * --rw-stale.
 */
(function () {
  "use strict";
  if (typeof customElements === "undefined" || customElements.get("robohub-widget")) {
    return;
  }

  var STYLE =
    ":host{--rw-bg:#fff;--rw-fg:#1d2329;--rw-muted:#5b6670;--rw-line:#d9dee3;--rw-accent:#0f8f86;--rw-stale:#a5620f;" +
    "display:inline-block;box-sizing:border-box;min-width:10em;padding:.6em .8em;border:1px solid var(--rw-line);" +
    "border-radius:10px;background:var(--rw-bg);color:var(--rw-fg);font:14px/1.35 system-ui,-apple-system,'Segoe UI',sans-serif}" +
    "@media (prefers-color-scheme:dark){:host{--rw-bg:#161b20;--rw-fg:#e6eaee;--rw-muted:#9aa5ae;--rw-line:#2b333a;" +
    "--rw-accent:#3cc4b8;--rw-stale:#e0a040}}" +
    ".t{font-size:.78em;color:var(--rw-muted);margin:0 0 .2em}.v{font-size:1.9em;font-weight:600;line-height:1.1}" +
    ".u{font-size:.55em;font-weight:500;color:var(--rw-muted);margin-left:.2em}.at{font-size:.72em;color:var(--rw-muted)}" +
    ".stale .v,.stale td.n{color:var(--rw-stale)}.flag{display:inline-block;font-size:.68em;font-weight:700;" +
    "letter-spacing:.05em;text-transform:uppercase;color:var(--rw-stale);border:1px solid var(--rw-stale);border-radius:4px;" +
    "padding:0 .3em;margin-left:.4em;vertical-align:middle}table{border-collapse:collapse;width:100%}" +
    "caption{text-align:left}td{padding:.25em .4em;border-top:1px solid var(--rw-line);text-align:left}" +
    "td.n{text-align:right;font-weight:600;white-space:nowrap}svg{display:block;width:100%;height:3em;margin-top:.3em}" +
    "polyline{fill:none;stroke:var(--rw-accent);stroke-width:2;vector-effect:non-scaling-stroke}" +
    ".stale polyline{stroke:var(--rw-stale)}.err{color:var(--rw-muted);font-size:.85em;margin:0}";

  function esc(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function shown(value) {
    return value === null || value === undefined ? "—" : String(value);
  }

  function when(at) {
    var d = at ? new Date(at) : null;
    return d && !isNaN(d.getTime()) ? d.toLocaleString() : "";
  }

  function flag(item) {
    return item.stale ? '<span class="flag" title="' + esc(when(item.at)) + '">stale</span>' : "";
  }

  // A sparkline of an item's history as an inline SVG: the values scaled into
  // a 100 x 30 box, oldest on the left.
  function sparkline(history) {
    var points = (history || []).filter(function (p) {
      return Array.isArray(p) && typeof p[1] === "number" && isFinite(p[1]);
    });
    if (points.length < 2) {
      return "";
    }
    var low = Math.min.apply(null, points.map(function (p) { return p[1]; }));
    var high = Math.max.apply(null, points.map(function (p) { return p[1]; }));
    var span = high - low || 1;
    var step = 100 / (points.length - 1);
    var line = points.map(function (p, i) {
      return (i * step).toFixed(2) + "," + (28 - ((p[1] - low) / span) * 26).toFixed(2);
    }).join(" ");
    return '<svg viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label="history">' +
      '<polyline points="' + line + '"/></svg>';
  }

  function single(item, kind) {
    return '<div class="' + (item.stale ? "one stale" : "one") + '"><p class="t">' + esc(item.label) + flag(item) + "</p>" +
      '<div class="v">' + esc(shown(item.value)) + (item.unit ? '<span class="u">' + esc(item.unit) + "</span>" : "") + "</div>" +
      (kind === "chart" ? sparkline(item.history) : "") +
      '<div class="at">' + esc(when(item.at)) + "</div></div>";
  }

  function table(snapshot, items) {
    var rows = items.map(function (item) {
      return '<tr class="' + (item.stale ? "stale" : "") + '"><td>' + esc(item.label) + flag(item) + '</td><td class="n">' +
        esc(shown(item.value)) + (item.unit ? " " + esc(item.unit) : "") + "</td></tr>";
    }).join("");
    return '<table><caption class="t">' + esc(snapshot.title || "") + "</caption><tbody>" + rows + "</tbody></table>" +
      '<div class="at">' + esc(when(snapshot.updated_at)) + "</div>";
  }

  class RobohubWidget extends HTMLElement {
    static get observedAttributes() {
      return ["src", "item", "kind"];
    }

    constructor() {
      super();
      this._root = this.attachShadow({ mode: "open" });
      this._timer = null;
      this._snapshot = null;
    }

    connectedCallback() {
      this._load();
    }

    disconnectedCallback() {
      this._stop();
    }

    attributeChangedCallback() {
      if (this.isConnected) {
        this._load();
      }
    }

    _stop() {
      if (this._timer !== null) {
        clearTimeout(this._timer);
        this._timer = null;
      }
    }

    _load() {
      var self = this;
      var src = this.getAttribute("src");
      this._stop();
      if (!src) {
        this._draw(null);
        return;
      }
      // No cookie, no authorization, no referrer: the snapshot is public and
      // the request says nothing of the page or its visitor.
      fetch(src, { credentials: "omit", cache: "no-cache", referrerPolicy: "no-referrer" })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("HTTP " + response.status);
          }
          return response.json();
        })
        .then(function (snapshot) {
          if (!snapshot || snapshot.format !== "robohub-feed" || snapshot.schema !== 1 || !Array.isArray(snapshot.items)) {
            throw new Error("not a robohub-feed snapshot");
          }
          self._snapshot = snapshot;
        })
        .catch(function () {
          // What was shown stays, every item marked stale: whatever the reason,
          // it is not current.
          if (self._snapshot) {
            self._snapshot.items.forEach(function (item) { item.stale = true; });
          }
        })
        .then(function () {
          self._draw(self._snapshot);
          var every = self._snapshot && Number(self._snapshot.refresh) >= 30 ? Number(self._snapshot.refresh) : 60;
          self._timer = setTimeout(function () { self._load(); }, every * 1000);
        });
    }

    _draw(snapshot) {
      var body;
      if (!snapshot) {
        body = '<p class="err">unavailable</p>';
      } else {
        var key = this.getAttribute("item");
        var kind = this.getAttribute("kind") || (key ? "number" : "table");
        var items = key ? snapshot.items.filter(function (item) { return item.key === key; }) : snapshot.items;
        if (!items.length) {
          body = '<p class="err">no item ' + esc(key || "") + "</p>";
        } else if (kind === "table") {
          body = table(snapshot, items);
        } else {
          body = items.map(function (item) { return single(item, kind); }).join("");
        }
      }
      this._root.innerHTML = "<style>" + STYLE + "</style>" + body;
    }
  }

  customElements.define("robohub-widget", RobohubWidget);
})();
