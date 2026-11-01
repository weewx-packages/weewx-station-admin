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

The **Station** page offers these kinds of station. It installs the driver from the
catalog when you choose one that the station does not have yet.

| Kind of station | Driver |
|---|---|
| Davis, through an RTL-SDR dongle | [`rtldavis`](https://github.com/weewx-packages/catalog/blob/main/packages/rtldavis.md) |
| Davis, through a WeatherLink logger | `Vantage`, part of WeeWX |
| Davis WeatherLink Live | [`wll`](https://github.com/weewx-packages/catalog/blob/main/packages/wll.md) |
| Davis WeatherLink Console, through the cloud | [`davis-cloud`](https://github.com/weewx-packages/catalog/blob/main/packages/davis-cloud.md) |
| Ecowitt or Froggit console, sending to this station | [`ecowittcustom`](https://github.com/weewx-packages/catalog/blob/main/packages/ecowittcustom.md) |
| Ecowitt or Froggit console, read over the network | [`ecowittgateway`](https://github.com/weewx-packages/catalog/blob/main/packages/ecowittgateway.md) |
| Ambient Weather console | [`ambient-http-push`](https://github.com/weewx-packages/catalog/blob/main/packages/ambient-http-push.md) |
| WeatherFlow Tempest | [`tempest-udp`](https://github.com/weewx-packages/catalog/blob/main/packages/tempest-udp.md) |
| Netatmo, through the cloud | [`netatmo`](https://github.com/weewx-packages/catalog/blob/main/packages/netatmo.md) |
| Simulated station | `Simulator`, part of WeeWX |

## Limitations

- The page uses plain HTTP, so the password crosses your network unencrypted.
- The first visitor chooses the password.
- None of these drivers has been tested on the image with real weather hardware.
- Choosing a driver from the catalog needs a connection to the internet.
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
