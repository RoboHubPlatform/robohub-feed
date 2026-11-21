# RoboHub Feed

The RoboHub feed application: chosen readings of an installation — from Mesh,
Aquarium, Energy — published outward as static JSON snapshots and one
dependency-free widget script, so pages of other sites can show them without
reaching the installation (robohub ADR-0019, SYS-0071).

A **feed** is an explicit selection of readings, each with a label and a unit.
On every refresh Feed reads each item from the application that holds it, with a
read-only service token, builds one snapshot per feed — labels, values, units and
times, nothing that names the installation — and hands it with `widget.js` to the
feed's **publishers**: `directory`, a folder on this machine that a web server or
a sync tool serves, or `http`, a site elsewhere that takes each file with an
HTTPS `PUT` and the publisher's bearer token. Other sites read only those files;
a reading that stops arriving is shown as stale.

This repository sits beside the orchestrator, `robohub`, which carries the shared
modules it uses (`ui`, `i18n`, `forms`, `notifications`, `settings`, `logging`)
and the sign-in plugin. Feed's own code is in `src/feed/` (its rules, which read no
file, in `src/feed/domain/`), the widget in `static/widget.js`, and the snapshot's
schema in `schemas/feed.v1.json`.

## How the keeper runs it

Feed is `kind: keeper-hosted`, on `127.0.0.1:8484`. Its manifest says
`deploy.calls: [mesh, aquarium, energy]`, so the keeper registers it as a client
of those three alone and gives it their addresses (`RHO_SERVICE_<NAME>_URL`), its
client id and secret, and the issuer (`RHO_AUTH_URL`); Feed asks each for a
read-only scope and nothing more. A person reaches its pages through the keeper's
sign-in with the grant `feed:read` (look) or `feed:*` (change). The keeper
supervises it like any application (robohub ADR-0018).

## Building and running

```sh
rho build .
```

From a terminal, on its own (no keeper: this machine only, every grant):

```sh
RHO_AUTH_STANDALONE=1 RHO_APP_WORKSPACE=/tmp/feed RHO_HTTP_ADDR=127.0.0.1:8484 ./build/feed
```

Without `RHO_SERVICE_*_URL` and a client credential nothing can be read, and every
item stays stale.

## Embedding a widget

Point a web server (or a sync tool) at a directory publisher's folder — `public/`
in Feed's workspace by default, or a folder of your choice on the Publishers page
— then, on any page:

```html
<script src="https://example.org/robohub/widget.js" defer></script>
<robohub-widget src="https://example.org/robohub/feeds/<feed id>.json" kind="table"></robohub-widget>
<robohub-widget src="https://example.org/robohub/feeds/<feed id>.json" item="i1" kind="chart"></robohub-widget>
```

`kind` is `number`, `chart` or `table`; `item` is an item's key (`i1`, `i2` …, by
position). A feed's Preview page shows the widget with exactly what would be
published, and the lines to embed. The widget fetches without credentials, stores
nothing and loads nothing else.

## Tests

```sh
rho test .
```

The Rho unit tests hold the rules (ids, intervals, staleness, the snapshot, the
privacy check, publisher folders, the http publisher's addresses and tokens,
grants); `tests/feed_smoke.py` runs the built application beside stand-ins for
Mesh, an appapi application and the token issuer and checks every snapshot it
writes against the schema; `tests/http_publisher_smoke.py` runs it beside a
local receiver for the http publisher; and
`tests/widget_test.py` runs `widget.js` under node with a stand-in DOM.

## Documentation

[docs/doc/index.md](docs/doc/index.md), built into the RoboHub site and served by
the running application under Documentation. The decisions inside Feed are in
[docs/architecture/adr/](docs/architecture/adr/), its requirements in
[docs/requirements/feed.yml](docs/requirements/feed.yml).

## License

MIT. See [LICENSE](LICENSE).
