# WeeWX station administration

A web page for running a WeeWX station without a terminal: status and log, station
settings, sensor assignment, database columns, extensions, reports, uploads to
weather services, and backups. It is the administration of the
[WeeWX station image](https://github.com/weewx-packages/weewx-station-image) and
expects that image's services. It does not work as a plain extension on another
system.

This is an own project of the weewx-packages organization.

## Requirements

- The WeeWX station image. It provides the service that runs the page, nginx in
  front of it, and the helper for the few actions that need root.

## Installation

The image contains this package. Install updates on the page under **Extensions**,
or with the [WeeWX packages catalog](https://github.com/weewx-packages/catalog/blob/main/packages/station-admin.md).
The catalog page lists the current release, its WeeWX and Python
requirements, and the install, update and removal commands.

## Configuration

The administration has no options. It listens on port 8377 of the loopback
interface, and nginx forwards `/admin/` to it from the local network only.

## Limitations

- The page uses plain HTTP, so the password crosses your network unencrypted.
- The first visitor chooses the password.
- Installers of extensions run on the station with the rights of the `weewx`
  account. Install only what you trust.

## Development

```sh
python -m pytest -q tests
```

Run it in an environment with WeeWX and pytest, with `bin` on `PYTHONPATH`.

## License

Copyright (c) 2026 Manuel Hilgert. Distributed under the GNU General Public License,
version 3 or later.
