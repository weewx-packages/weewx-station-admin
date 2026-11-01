# Changelog

## Unreleased

The station page offers more kinds of station: Davis through a WeatherLink logger,
WeatherLink Live and the WeatherLink cloud, Ecowitt and Froggit read over the network,
Ambient Weather, WeatherFlow Tempest, Netatmo and a simulated station. A driver from
the catalog is installed when it is chosen, so this step needs the internet.

The fields of the chosen station now stand right below the choice.

The status page no longer shows `nullnull` before the first readings. A refresh that
was under way no longer replaces the tab you just opened. Secrets entered on the station
page stay on the server, and an empty field keeps the stored value.

## 0.1.0a3 - 2026-10-31

Choose the language of the weather pages on the station page. It offers the locales the
system has, and sets `lang` and `belchertown_locale` of the Belchertown report.

## 0.1.0a2 - 2026-10-30

Wait for the server when the page loads during a restart, instead of staying empty.

## 0.1.0a1 - 2026-10-30

First release.
