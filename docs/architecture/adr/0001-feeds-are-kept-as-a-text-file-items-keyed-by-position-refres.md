---
id: ADR-0001
title: Feeds are kept as a text file, items keyed by position, refreshed by one loop
status: accepted
date: 2026-11-20
requirements: [FEED-0001, FEED-0003, FEED-0004, FEED-0006]
supersedes: []
superseded_by: []
---

# Feeds are kept as a text file, items keyed by position, refreshed by one loop

## Context

robohub ADR-0019 decided that a separate application publishes chosen readings
outward as static snapshots; FEED-0001..0007 say what it keeps and publishes.
Three choices inside the application are not settled by them and shape its code:
where the feeds are kept, what an item is called in a public snapshot, and how
refreshes are run. A fourth follows from what Mesh offers: a Mesh source's value
answers no history (FEED-0002 names only `/value` for Mesh), yet an item may have
a history window (FEED-0001).

## Decision

1. **Storage: one text file in the workspace.** `feeds.txt` in
   `RHO_APP_WORKSPACE` holds the feeds, their items in order and the publishers,
   a record per line with `|`-separated, percent-encoded fields; each feed's last
   readings, history points and publish status are `state/<id>.txt`. Every write
   replaces the file in one step (written beside it, renamed over), and a change
   to `feeds.txt` is made under one lock. There are tens of records, read whole
   on every refresh; a file the person can read and back up with the workspace
   fits better than tables, and keeps the rules (`src/feed/domain`) plain text
   functions tested on the C backend. The SQLite database the application has is
   the notifications module's alone.
2. **An item's key is its position**: `i1`, `i2` … in the order the feed lists
   them. A key derived from the source (a hash of the project and source, say)
   would be stable across edits but would let anyone who reads two snapshots tell
   that two items read the same thing, and a guessable one would name it; a
   position says nothing. Removing an item moves the keys after it — the feed's
   page says so — and a widget showing one item by key then shows the next.
3. **One refresh loop, one refresh at a time.** The `background` goroutine looks
   every 5 s and refreshes each enabled feed whose interval (30 s at least) has
   passed since its last refresh; "Publish now" runs the same refresh at once from
   the page. Both take one lock, so two refreshes never interleave their state or
   their files; deleting a feed takes it too, so no refresh publishes a feed that
   is going. A failed publish is recorded and retried by the next refresh — no
   retry timer of its own.
4. **A Mesh item's history is what Feed read itself.** For an item with a window
   that reads Mesh, each refresh's numeric reading is kept as a point (a day of 30 s
   readings at most); an appapi item's history is fetched from its application
   (`/values/{id}/history`). A snapshot carries at most 96 points per item, spread
   evenly over the window.
5. **A snapshot is checked before it is handed out.** It is built only from the
   feed's id and title, labels, units, values and times; before publishing, a
   refresh searches it for every item's application, project, source or value id
   and the called applications' addresses, the workspace and the home folder, and
   publishes nothing that holds one the person did not write into a label, unit or
   title.

## Consequences

- No migration or generated SQL for feeds; the file's format is the contract
  between versions of Feed and is versioned by its first line if it changes.
- Keys are not stable across edits of a feed; a page embedding one item by key
  must be updated when items before it are removed.
- Refreshes are serial: with many feeds whose sources are slow (each request has
  a 10 s limit), a refresh can be late by the sum of their waits.
- A Mesh item's history starts when the item is added and has gaps while Feed or
  Mesh is down; Mesh's own telemetry series is not read, which keeps Feed to the
  paths FEED-0002 names.
