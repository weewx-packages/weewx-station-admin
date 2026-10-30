# weewx-station-admin

Web administration of the WeeWX station image, delivered as a catalog package so it
updates like every other extension.

## Status

Alpha (before 1.0): smoke tests only, no backward compatibility.

## Checks

- `PYTHONPATH=bin python -m pytest -q tests`: about 2 seconds. Needs WeeWX and pytest.
- `node --check bin/user/station_admin/ui/app.js` after changing the page.

## Structure

- `bin/user/station_admin/server.py`: HTTP, sessions and routes.
- `bin/user/station_admin/ui/`: the page, without external resources.
- `bin/user/station_admin/live.py`: WeeWX service that writes the latest packet.
- `tools/package.py`: builds the release archive.

## Conventions

The service runs as `weewx`. Root actions go through `station-privileged` in
`weewx-station-image`; a new action needs a change there. WeeWX must have stopped
before the database changes, so `weewx-stop` blocks. Python follows the WeeWX style:
no annotations, Google docstrings with types. Text from the station reaches the page
only through `textContent`. Secrets never leave the server: the page can only
replace them.
