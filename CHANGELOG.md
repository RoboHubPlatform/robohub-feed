# Changelog

## [0.2.0] - 2026-11-21

An `http` publisher (FEED-0008, robohub ADR-0026, 3), so a feed's files reach a
site elsewhere — a nest site's `nest-feed` module — while nothing at the
installation is reachable from outside.

- **`http` publishers** send each file of a refresh — `widget.js`,
  `example.html` and `feeds/<id>.json`, the set and names a directory publisher
  writes — with a `PUT` to the publisher's base URL followed by the file's name,
  carrying `Authorization: Bearer <token>`. The base URL is `https://`; plain
  `http://` only to the loopback, for tests; a user, query or fragment is
  refused.
- **The token** is set on the publisher's form and kept in
  `publisher-<name>.token` beside the feed file, owner-only: never in
  `feeds.txt`, never shown again (the page says *set* or *not set*), never on a
  command line, in an error or in the log; it reaches curl through a
  configuration file written owner-only for one request and removed after it.
  Removing the publisher removes its token.
- **Done means 2xx**: a publish counts only when every `PUT` is answered 2xx
  within 15 s (10 s to connect, no redirect followed); any other answer is
  recorded with its HTTP status, or as no answer with curl's error, and the next
  refresh tries again.
- The Publishers page offers kind `http`, a base URL and a token, and shows
  whether each http publisher has its token.
- `tests/http_publisher_smoke.py` runs Feed beside a receiver on 127.0.0.1.
- `widget.js` styles itself with a constructed stylesheet adopted by its shadow root, not a `<style>` element. A page whose Content Security Policy has no `unsafe-inline` for styles, such as a nest site's `style-src 'self'`, blocks that element and drew the widget unstyled. A browser without constructed stylesheets still gets the element.

## [0.1.0] - 2026-11-20

The first version of Feed (robohub ADR-0019, SYS-0071; FEED-0001..0007): chosen
readings of the installation published outward as static snapshots and a widget
script, a keeper application on `127.0.0.1:8484` that calls Mesh, Aquarium and
Energy.

- **Feeds** with a title, an id of 24 random hexadecimal characters, a refresh
  interval of 30 s at least, enabled or not, their publishers and up to 24 items —
  a label, a source picked from what Mesh (projects and sources) and the appapi
  applications (values) list, a unit, decimals and a history window (none, 1 h,
  24 h). Kept as a text file in the workspace (ADR-0001).
- **Refreshing**: one loop refreshes each enabled feed at its interval, and
  Publish now at once; each reading is asked with a token for its application's
  audience and a read-only scope (`mesh:<project>:read`, `<app>:read`), and only
  from the applications `deploy.calls` lists.
- **Snapshots** `feeds/<id>.json` — `format`, `schema: 1`, id, title,
  `updated_at`, `refresh` and the items (key by position, label, value, unit,
  `at`, `stale`, history) — and nothing that names the installation, checked
  before publishing; described by `schemas/feed.v1.json`.
- **Staleness**: older than three intervals or 5 minutes, whichever is longer; a
  source that cannot be read keeps its last value, marked stale, and the snapshot
  is still published.
- **`widget.js`**: `<robohub-widget src item kind>`, number, chart (an inline SVG
  sparkline) or table, fetched without credentials, refreshed at the snapshot's
  interval, stale marking, light and dark through CSS custom properties; it
  stores and loads nothing else.
- **Publishers**: the `directory` kind, each file written beside its target and
  renamed into place, a failure recorded with its reason and retried at the next
  refresh; other kinds refused until they exist; folders limited to plain,
  non-system, non-hidden paths. A default `local` publisher writes into the
  workspace's `public/`.
- **Pages**, behind the keeper's sign-in (`feed:read` to look, `feed:*` to
  change): the feeds with their last refresh, last publish and error; making,
  editing, disabling and deleting a feed (which removes its snapshot from its
  directory publishers); the items and the source picker; the preview; the
  publishers. Every change is a form with the form token.

Mesh items need Mesh 0.24.0 or later, which accepts the read-only `mesh:<project>:read` on its read paths (MESH-API-0002).
