# Changelog

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
