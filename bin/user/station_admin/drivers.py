# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""The kinds of station on the station page, and what each one needs in weewx.conf.

A driver is described by data, so adding one needs no code in the page. Its fields say
what the form asks for and which option of the driver's section receives the answer.
The drivers without a `package` are in the image or in WeeWX itself. The others are
installed from the catalog when somebody chooses them, which lets a new driver reach
stations that already run.
"""

import json
import os
import re

from user.station_admin import common
from user.station_admin.i18n import N_, _

# weewx.conf holds these as they are, and a host, a device or a key never has spaces.
PLAIN_VALUE = re.compile(r'^[\x21-\x7e]+$')
# What installers and default stanzas of the drivers write before anybody has chosen a
# value. They must not appear in the form as if they were answers.
PLACEHOLDER = re.compile(r'^(INSERT_|REPLACE_|replace_me$|1\.2\.3\.4$)')
LOWEST_PORT = 1024
HIGHEST_PORT = 65535


def _text(name, label, option, default='', optional=False, when=None):
    return dict(name=name, label=label, kind='text', option=option, default=default,
                optional=optional, when=when)


def _port(default):
    return dict(name='port', label=N_('Port'), kind='port', option='port', default=default,
                optional=False, when=None)


def _secret(name, label, option):
    return dict(name=name, label=label, kind='secret', option=option, default='',
                optional=False, when=None)


def _choice(name, label, option, choices, default):
    return dict(name=name, label=label, kind='choice', option=option, choices=choices,
                default=default, optional=False, when=None)


def _netatmo_tokens():
    """Return the file that holds the refresh token of Netatmo.

    The driver keeps the token outside weewx.conf, because every refresh replaces it.
    """
    return os.path.join(os.path.dirname(common.CONFIG_PATH), 'netatmo-tokens.json')


DRIVERS = {
    'rtldavis': dict(
        title=N_('Davis, through an RTL-SDR dongle'), module='user.rtldavis', section='Rtldavis',
        fields=(
            _choice('band', N_('Frequency band'), 'transceiver_frequency',
                    {'EU': 'EU, 868 MHz', 'US': 'US, 915 MHz', 'NZ': 'NZ, 921 MHz'}, 'EU'),
            _choice('channel', N_('ISS channel, as shown on the console'), 'iss_channel',
                    {str(number): str(number) for number in range(1, 9)}, '1'),
            _choice('bucket', N_('Rain bucket'), 'rain_bucket_type',
                    {'1': N_('0.2 mm per tip'), '0': N_('0.01 inch per tip')}, '1'))),
    'vantage': dict(
        title=N_('Davis, through a WeatherLink logger'), module='weewx.drivers.vantage',
        section='Vantage',
        fields=(
            _choice('connection', N_('Connection to the logger'), 'type',
                    {'serial': N_('USB or serial'),
                     'ethernet': N_('Network (WeatherLinkIP)')}, 'serial'),
            _text('device', N_('Device of the logger'), 'port', '/dev/ttyUSB0',
                  when=('connection', 'serial')),
            _text('host', N_('Address of the logger'), 'host', when=('connection', 'ethernet')))),
    'wll': dict(
        title=N_('Davis WeatherLink Live'), module='user.wll', section='WLL', package='wll',
        fields=(_text('host', N_('Address of the WeatherLink Live'), 'host'),),
        note=N_('Give the WeatherLink Live a fixed address in your router.')),
    'davis-cloud': dict(
        title=N_('Davis WeatherLink Console, through the WeatherLink cloud'),
        module='user.daviscloud.driver', section='DavisCloud', package='davis-cloud', pre=True,
        # WeeWX makes the records. The other way, reading them from the cloud archive,
        # needs historic access on the WeatherLink account, which this page cannot check.
        archive='software',
        fields=(_secret('api_key', N_('API key'), 'api_key'),
                _secret('api_secret', N_('API secret'), 'api_secret'),
                _text('station_id', N_('Station ID, only for an account with several stations'),
                      'station_id', optional=True)),
        note=N_('Create the API key and secret on weatherlink.com, under Account.')),
    'ecowitt': dict(
        title=N_('Ecowitt or Froggit console, sending to this station'),
        module='user.ecowittcustom', section='Ecowittcustom',
        fields=(_port('8080'),),
        note=N_('In WS View Plus under Weather Services, Customized, set: protocol Ecowitt, '
                'server {address}, path /, this port, interval 60 seconds.')),
    'ecowitt-gateway': dict(
        title=N_('Ecowitt or Froggit console, read over the network'),
        module='user.weewx-EcowittGateway', section='EcowittGateway', package='ecowittgateway',
        fields=(_text('host', N_('Address of the console or gateway'), 'ip_address'),),
        note=N_('Give the console a fixed address in your router. Nothing has to be set on it.')),
    'ambient': dict(
        title=N_('Ambient Weather console'), module='user.ambient_http_push',
        section='AmbientHTTPPush', package='ambient-http-push', pre=True,
        fields=(_port('8080'),),
        note=N_('In the awnet app under Device Settings, Customized Upload, set: protocol '
                'Ambient Weather, server {address}, path /data?, this port, interval 60 seconds.')),
    'tempest': dict(
        title=N_('WeatherFlow Tempest'), module='user.tempest_udp', section='TempestUDP',
        package='tempest-udp', pre=True, fields=(),
        note=N_('Nothing has to be set. The hub must be on the same network as this station.')),
    'netatmo': dict(
        title=N_('Netatmo, through the Netatmo cloud'), module='user.netatmo', section='netatmo',
        package='netatmo',
        fields=(_text('client_id', N_('Client ID'), 'client_id'),
                _secret('client_secret', N_('Client secret'), 'client_secret'),
                _secret('refresh_token', N_('Refresh token'), None)),
        note=N_('Create an app on dev.netatmo.com. Its page shows the client ID and secret, '
                'and its token generator gives the refresh token, with the scope read_station.')),
    'simulator': dict(
        title=N_('Simulated station, to try this out'), module='weewx.drivers.simulator',
        section='Simulator', fields=(),
        note=N_('This station makes up its readings and stores them in the database.')),
}


def active(config):
    """Return the kind of station that weewx.conf selects.

    Args:
        config (configobj.ConfigObj): The configuration.

    Returns:
        str: The key in DRIVERS. Default is 'rtldavis', which the image starts with.
    """
    station_type = config['Station'].get('station_type')
    for key, driver in DRIVERS.items():
        if driver['section'] == station_type:
            return key
    return 'rtldavis'


def _stored(field, section):
    """Return the value weewx.conf holds for a field.

    Args:
        field (dict): The field.
        section (configobj.Section|dict): The section of the driver.

    Returns:
        str: The value. Empty if none has been chosen yet.
    """
    if field['name'] == 'refresh_token':
        return 'stored' if os.path.exists(_netatmo_tokens()) else ''
    value = section.get(field['option'], '')
    return '' if PLACEHOLDER.match(str(value)) else str(value)


def describe(config):
    """Return the kinds of station for the page.

    Args:
        config (configobj.ConfigObj): The configuration.

    Returns:
        list[dict]: For each kind its key, title, note and fields. A field of the kind
            'secret' only says whether a value is stored, because secrets never leave
            this server.
    """
    kinds = []
    for key, driver in DRIVERS.items():
        section = config.get(driver['section'], {})
        fields = []
        for field in driver['fields']:
            stored = _stored(field, section)
            entry = {name: value for name, value in field.items() if name != 'option'}
            entry['label'] = _(field['label'])
            if 'choices' in field:
                entry['choices'] = {key: _(text) for key, text in field['choices'].items()}
            if field['kind'] == 'secret':
                entry.update(value='', stored=bool(stored))
            else:
                entry['value'] = stored or field['default']
            fields.append(entry)
        note = _(driver['note']) if 'note' in driver else None
        kinds.append(dict(key=key, title=_(driver['title']), note=note, fields=fields))
    return kinds


def _applies(field, form):
    return field['when'] is None or form.get(field['when'][0]) == field['when'][1]


def parse(key, form, config):
    """Validate the fields of one kind of station.

    Args:
        key (str): The key in DRIVERS.
        form (dict): Submitted values.
        config (configobj.ConfigObj): The configuration, to know the stored secrets.

    Returns:
        tuple[dict, list[str]]: A two-way tuple (values, errors). The values are keyed
            by field name, and an empty secret is left out to keep the stored one.
    """
    driver = DRIVERS[key]
    section = config.get(driver['section'], {})
    values = {}
    errors = []
    for field in driver['fields']:
        if not _applies(field, form):
            continue
        name = field['name']
        value = str(form.get(name, '')).strip()
        if field['kind'] == 'choice':
            if value not in field['choices']:
                errors.append(_('Choose: {label}.', label=_(field['label'])))
        elif field['kind'] == 'port':
            if not value.isascii() or not value.isdigit() \
                    or not LOWEST_PORT <= int(value) <= HIGHEST_PORT:
                errors.append(_('Port must be between {low} and {high}.', low=LOWEST_PORT,
                                high=HIGHEST_PORT))
        elif not value:
            if field['kind'] == 'secret' and _stored(field, section):
                continue
            if not field['optional']:
                errors.append(_('Enter: {label}.', label=_(field['label'])))
        elif not PLAIN_VALUE.match(value):
            errors.append(_('{label} holds a character that is not allowed.',
                            label=_(field['label'])))
        values[name] = value
    return values, errors


def needs_package(key):
    """Return the catalog package a kind of station still needs.

    Args:
        key (str): The key in DRIVERS.

    Returns:
        tuple[str, bool]|None: A two-way tuple (package id, whether prereleases are
            allowed), or None if nothing has to be installed.
    """
    driver = DRIVERS[key]
    if 'package' not in driver:
        return None
    path = os.path.join(common.USER_ROOT, *driver['module'].split('.')[1:]) + '.py'
    return None if os.path.exists(path) else (driver['package'], driver.get('pre', False))


def apply(key, config, values):
    """Write the values of a kind of station into the configuration.

    Args:
        key (str): The key in DRIVERS.
        config (configobj.ConfigObj): The configuration, changed in place.
        values (dict): The values from parse.
    """
    driver = DRIVERS[key]
    section = config.setdefault(driver['section'], {})
    section['driver'] = driver['module']
    for field in driver['fields']:
        value = values.get(field['name'], '')
        if field['option'] is None:
            continue
        if value:
            section[field['option']] = value
        elif field['optional']:
            # An installer leaves a placeholder here, which the driver would use.
            section.pop(field['option'], None)
    # 'hardware' is what every weewx.conf ships with, and WeeWX falls back to software
    # by itself where a driver has no archive. Only the entries in DRIVERS differ.
    config.setdefault('StdArchive', {})['record_generation'] = driver.get('archive', 'hardware')
    if key == 'netatmo':
        _write_netatmo(section, values)


def _write_netatmo(section, values):
    path = _netatmo_tokens()
    # The driver replaces the token at every refresh, so the file is only written when
    # somebody enters a new one. An older token no longer works.
    if values.get('refresh_token'):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(dict(refresh_token=values['refresh_token']), stream)
    section['mode'] = 'cloud'
    section['tokens_persistence_file'] = path
    # The installer still writes the login that Netatmo no longer accepts.
    section.pop('username', None)
    section.pop('password', None)
