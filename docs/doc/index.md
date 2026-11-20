# Feed

Feed publishes chosen readings of a RoboHub installation — a temperature from
Mesh, a pump's state from Aquarium, a power from Energy — outward, as static JSON
snapshots and one small widget script, so pages of other sites can show them.
Those pages, and their visitors, never reach the installation: they read only
the files a publisher put somewhere (robohub ADR-0019, SYS-0071).

Feed is a keeper application like Mesh, Aquarium and Energy: the keeper runs it
on `127.0.0.1:8484`, signs a person in to it, and gives it the addresses of the
applications it reads from and the credential to ask them for tokens.

## Feeds and items

A **feed** is an explicit selection of readings. It has:

- a **title**, shown by the widget's table;
- an **id**, 24 random hexadecimal characters Feed makes when the feed is
  created. It is the snapshot's file name, and it cannot be guessed, so one
  feed's address does not lead to another's;
- a **refresh interval**, 30 seconds at the least;
- whether it is **enabled** — a disabled feed is neither refreshed nor published,
  and its last snapshot ages into staleness where it is;
- its **publishers**, where its files go;
- its **items**, at most 24.

An **item** is one reading: a **label** (what the widget shows), a **source**, an
optional **unit**, an optional number of **decimals** (0 to 3; without it the
value is shown as read, to the thousandth) and an optional **history** window —
none, 1 hour or 24 hours.

An item's **source** is picked on the feed's page from what the applications
Feed calls offer:

| Application | What is listed | What is read |
|---|---|---|
| Mesh | every project's sources (`/mesh/api/projects`, `/mesh/api/projects/{project}/sources`) | `/mesh/api/projects/{project}/sources/{source}/value` |
| Aquarium, Energy (appapi) | the application's values (`/api/v1/values`) | `/api/v1/values/{id}`, and `/api/v1/values/{id}/history` for an item with history |

An application that does not answer is named under the picker. Only the
applications in the manifest's `deploy.calls` (`mesh`, `aquarium`, `energy`) are
ever asked, whatever else the environment names.

## Refreshing

Every enabled feed is refreshed when its interval has passed: Feed reads each
item from the application that holds it, with a service token for that
application's audience and a **read-only scope** — `mesh:<project>:read` for a
Mesh source (`mesh:read` to list projects), `<app>:read` for an appapi value — so
it can read what it publishes and change nothing. It then builds the feed's
snapshot and hands it, with `widget.js`, to the feed's publishers. **Publish
now** on a feed's page does the same at once.

A Mesh source answers no time, so its reading is timed when it was asked; an
appapi value carries the time it was updated. A Mesh item's history is the
readings Feed took of it itself (it starts when the item is added); an appapi
item's history comes from its application.

## The snapshot

`feeds/<id>.json`, one per enabled feed, described by
[`schemas/feed.v1.json`](../../schemas/feed.v1.json) (JSON Schema 2020-12):

```json
{
  "format": "robohub-feed",
  "schema": 1,
  "id": "3562e0ec0ae37ee0876c5f3b",
  "title": "Garden",
  "updated_at": "2026-11-20T10:00:00Z",
  "refresh": 60,
  "items": [
    {"key": "i1", "label": "Air", "value": 21.5, "unit": "°C",
     "at": "2026-11-20T09:59:58Z", "stale": false,
     "history": [["2026-11-20T09:00:00Z", 21.1], ["2026-11-20T09:59:58Z", 21.5]]},
    {"key": "i2", "label": "Pump", "value": "on", "unit": "",
     "at": "2026-11-20T09:59:40Z", "stale": false}
  ]
}
```

- `updated_at` is when the snapshot was made, `at` when each reading was taken,
  both UTC in ISO 8601; `at` is null before an item's first reading.
- `refresh` is the feed's interval in seconds; the widget fetches the snapshot
  again after it.
- `value` is a number, a string for a word state such as `on`, or null before the
  first reading.
- `history`, for an item with a window, is `[time, value]` pairs, oldest first,
  at most 96, spread evenly over the window.
- `key` is the item's **position** in the feed — `i1` for the first. Removing an
  item moves the keys of the items after it.

A snapshot holds labels, values, units and times **and nothing else**: no
application, project, node or source identifier, no address, no token. Before a
snapshot is handed to a publisher, Feed searches it for each item's application,
project, source or value id and for the called applications' addresses; a
snapshot that holds one the person did not write into a label, unit or title is
not published, and the feed's error says so.

## Staleness

An item is **stale** when its reading is older than three refresh intervals or
5 minutes, whichever is longer, or when its source could not be read at the last
refresh. A source that cannot be read keeps its last value, marked stale, and the
snapshot is still published: a widget never shows a frozen value as current, nor
goes blank because one source failed. The feeds list counts each feed's readings
that are not current.

## The widget

`widget.js` is one script with no dependency. It defines a custom element:

```html
<script src="https://example.org/robohub/widget.js" defer></script>

<robohub-widget src="https://example.org/robohub/feeds/3562e0ec0ae37ee0876c5f3b.json"
                kind="table"></robohub-widget>
<robohub-widget src="https://example.org/robohub/feeds/3562e0ec0ae37ee0876c5f3b.json"
                item="i1" kind="number"></robohub-widget>
<robohub-widget src="https://example.org/robohub/feeds/3562e0ec0ae37ee0876c5f3b.json"
                item="i1" kind="chart"></robohub-widget>
```

| Attribute | What it is |
|---|---|
| `src` | the snapshot's address |
| `item` | an item's key (`i1`, `i2` …), or none for every item |
| `kind` | `number`, `chart` (a sparkline of the item's history) or `table`; `table` when there is no `item`, `number` when there is |

It fetches the snapshot **without credentials** and without a referrer, draws it
in its own shadow root, fetches it again at the snapshot's `refresh` interval,
marks a stale item `stale` (and every item, when the snapshot can no longer be
fetched), and follows the page's light or dark scheme. It stores nothing, sets no
cookie and loads nothing but the snapshot. Its colours are CSS custom properties
a page may set on the element:

```css
robohub-widget { --rw-bg: transparent; --rw-accent: #c0392b; }
```

(`--rw-bg`, `--rw-fg`, `--rw-muted`, `--rw-line`, `--rw-accent`, `--rw-stale`.)

The site serving the files must allow the embedding page to fetch them: on
another origin, the snapshot needs an `Access-Control-Allow-Origin` header from
the hosting (no credentials are ever sent, so `*` is enough).

A feed's **Preview** draws the widget — the whole feed as a table, and each item
on its own — with the snapshot that would be published now, from the last
readings, and shows the lines to embed. Nothing is published from the preview.

## Publishers

A publisher receives the files of one refresh — the feed's snapshot,
`widget.js` and a small `example.html` — and puts each in place **atomically**:
written beside its target under a hidden temporary name, then renamed over it, so
a web server or a sync tool never reads half a file. A feed names its publishers;
a publisher that fails is recorded on the feed with its reason and tried again at
the next refresh, and the other publishers are not held up.

The first kind is **`directory`**, a folder on this machine — for a local web
server, a sync tool, or testing. Feed starts with one, `local`, writing into
`public/` in its workspace. A directory publisher writes only to an absolute,
plain path: not the root, a system folder, the home folder itself, or anything
under a hidden folder (which keeps `~/.rho`, `~/.ssh` and `~/.config` out of
reach), except inside Feed's workspace. Publishers of other kinds — git (GitHub
Pages), ssh/rsync, S3 — are refused until they exist; each will be a decision of
its own about the credential it needs.

In a publisher's folder:

```text
widget.js
example.html          open as example.html#<feed id>
feeds/<id>.json       one per feed that names the publisher
```

Deleting a feed removes its snapshot from its directory publishers; taking a
publisher off a feed removes the feed's snapshot from that publisher.
`example.html` names no feed, so it cannot lead from one feed to another.

## Access

Feed's pages are behind the keeper's sign-in. **`feed:read`** lets a person look
at the feeds, their status and previews; **`feed:*`** lets them create, change,
disable, publish and delete feeds and publishers. Every change is a form posted
from Feed's own pages with their form token, and is answered with a redirect, so
reloading a page changes nothing again.

## Where Feed keeps things

In its workspace:

| Path | What it is |
|---|---|
| `feeds.txt` | the feeds, their items and the publishers, one record per line |
| `state/<id>.txt` | a feed's last readings, history and publish status |
| `public/` | the `local` publisher's folder |
| `data/app.db` | the notifications a page shows as toasts |

## Mesh version

Mesh items need Mesh 0.24.0 or later, whose `/mesh/api` accepts the read-only
`mesh:<project>:read` (and `mesh:read`) for the requests that only read
(MESH-API-0002). Against an older Mesh the picker lists no Mesh project and a
Mesh item reads as not available (stale); Feed does not ask for more than
reading. Aquarium's and Energy's appapi accept `<app>:read`.
