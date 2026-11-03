# Changelog

## Unreleased

On a phone the header keeps the link to the weather pages, the language and Log out
on one line.

## 0.1.0a11 - 2026-11-03

A new look: cards, a calmer header with tabs that scroll on a phone, a coloured state
on the status message, and a dark mode that follows the system. Current readings
carry the names the weather pages use, in the language of the page. The Raspberry Pi
section shows what needs attention as tiles and the rest as a list. Before the login
the empty tab bar no longer shows.

## 0.1.0a10 - 2026-11-03

The station page asks for the title of the weather pages. It follows the station name
until you type your own, and sets `site_title` and `manifest_name` of Belchertown.

## 0.1.0a9 - 2026-11-03

A Settings page edits weewx.conf and the settings of every report as forms, with the
comments of the files as help and a search. A setting of a skin, such as an option of
Belchertown, is stored in the section of its report in weewx.conf. It overrides the
skin.conf, survives updates of the skin, and can be set back to the skin's default.

Install an extension from a link under Extensions. A GitHub repository installs its
newest release, or its main branch if it has none. A link to a release, a branch or a
.zip or .tar.gz file installs exactly that. WeeWX's own installer does the work. A link
to a package of a catalog installs from the catalog.

Add, switch off and remove further catalogs under Extensions. The catalog list shows
the packages of every catalog that is on.

## 0.1.0a8 - 2026-11-03

A login survives a restart of the administration, such as after an update. A reboot
still ends it. Changing the password ends every other login.

## 0.1.0a7 - 2026-11-03

The page is in English and German. It follows the language of the browser, and a menu
at the top switches it. Messages of the server and of running operations follow the
same choice.

The status page has its own section for the Raspberry Pi: model, processor
temperature, power supply, disk, memory, running time, address, host name, system,
kernel and versions. It warns when the power supply is too weak.

The Sensors page shows the readings again, instead of NaN since 0.1.0a6. Its sensor
map now works: the page could not show the entries of the map or add one.

## 0.1.0a6 - 2026-11-03

The current readings on the status page are in the units of the weather pages, with
their unit. Before, they showed what the driver sent, such as °F for an Ecowitt console.
The temperature of the Raspberry Pi is now called Processor temperature.

## 0.1.0a5 - 2026-11-03

A login no longer ends when the station sets its clock after the start. Saving the
first settings of a new station failed with "Log in first." for this reason.

## 0.1.0a4 - 2026-11-01

The station page offers more kinds of station: Davis through a WeatherLink logger,
WeatherLink Live and the WeatherLink cloud, Ecowitt and Froggit read over the network,
Ambient Weather, WeatherFlow Tempest, Netatmo and a simulated station. A driver from
the catalog is installed when it is chosen, so this step needs the internet.

The fields of the chosen station now stand right below the choice.

The status page no longer shows `nullnull` before the first readings, or a message of
the previous driver after a change of station. A refresh that
was under way no longer replaces the tab you just opened. Secrets entered on the station
page stay on the server, and an empty field keeps the stored value.

## 0.1.0a3 - 2026-10-31

Choose the language of the weather pages on the station page. It offers the locales the
system has, and sets `lang` and `belchertown_locale` of the Belchertown report.

## 0.1.0a2 - 2026-10-30

Wait for the server when the page loads during a restart, instead of staying empty.

## 0.1.0a1 - 2026-10-30

First release.
