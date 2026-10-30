# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Reports, uploads to weather services, and the assignment of sensors."""

import re

from user.station_admin import common, settings, status

# The fields each service needs. A field of kind 'secret' is never sent to the
# page: it can only be replaced. Names are options in weewx.conf.
UPLOADS = {
    'Wunderground': dict(title='Weather Underground', fields=[
        ('station', 'text'), ('password', 'secret')]),
    'PWSweather': dict(title='PWSweather', fields=[('station', 'text'), ('password', 'secret')]),
    'WOW': dict(title='Met Office WOW', fields=[('station', 'text'), ('password', 'secret')]),
    'WOW-BE': dict(title='WOW Belgium', fields=[('station', 'text'), ('password', 'secret')]),
    'AWEKAS': dict(title='AWEKAS', fields=[('username', 'text'), ('password', 'secret')]),
    'CWOP': dict(title='CWOP', fields=[('station', 'text'), ('passcode', 'secret')]),
}
TRANSFERS = {
    'FTP': dict(title='Copy the website by FTP', fields=[
        ('server', 'text'), ('user', 'text'), ('password', 'secret'), ('path', 'text'),
        ('port', 'text')]),
    'RSYNC': dict(title='Copy the website by rsync', fields=[
        ('server', 'text'), ('user', 'text'), ('path', 'text')]),
}
OBSERVATION = re.compile(r'^[A-Za-z_][A-Za-z0-9_.-]*$')


def _describe(section, definition):
    values = {}
    secrets_set = []
    for name, kind in definition['fields']:
        if kind == 'secret':
            if section.get(name) not in (None, '', 'replace_me'):
                secrets_set.append(name)
        else:
            value = section.get(name, '')
            values[name] = '' if value == 'replace_me' else value
    return dict(title=definition['title'], enable=str(section.get('enable', 'false')).lower() == 'true',
                fields=[dict(name=name, kind=kind) for name, kind in definition['fields']],
                values=values, secrets_set=secrets_set)


def read_uploads(config):
    """Return the upload services for the page, without secrets.

    Args:
        config (configobj.ConfigObj): The configuration.

    Returns:
        dict: Services by section name.
    """
    restful = config.get('StdRESTful', {})
    report = config.get('StdReport', {})
    services = {name: _describe(restful.get(name, {}), definition)
                for name, definition in UPLOADS.items()}
    services.update({name: _describe(report.get(name, {}), definition)
                     for name, definition in TRANSFERS.items()})
    return services


def write_upload(config, name, form):
    """Change one upload service.

    Args:
        config (configobj.ConfigObj): The configuration.
        name (str): The section name.
        form (dict): enable and the values of the fields. An empty secret
            keeps the stored one.

    Raises:
        ValueError: The service is unknown.
    """
    if name in UPLOADS:
        definition, parent = UPLOADS[name], config.setdefault('StdRESTful', {})
    elif name in TRANSFERS:
        definition, parent = TRANSFERS[name], config['StdReport']
    else:
        raise ValueError('Unknown service.')
    section = parent.setdefault(name, {})
    section['enable'] = 'true' if form.get('enable') else 'false'
    if name in TRANSFERS:
        section.setdefault('skin', 'Ftp' if name == 'FTP' else 'Rsync')
    for field, kind in definition['fields']:
        value = str(form.get(field, '')).strip()
        if value or kind != 'secret':
            section[field] = value


def read_reports(config):
    """Return the reports of the station.

    Args:
        config (configobj.ConfigObj): The configuration.

    Returns:
        list[dict]: Name, skin, whether it is on, and its target directory.
    """
    report = config['StdReport']
    return [dict(name=name, skin=report[name].get('skin'),
                 enable=str(report[name].get('enable', 'false')).lower() == 'true',
                 html_root=report[name].get('HTML_ROOT', ''))
            for name in report.sections
            if name not in ('Defaults', 'FTP', 'RSYNC')]


def write_report(config, name, enable):
    """Switch a report on or off.

    Args:
        config (configobj.ConfigObj): The configuration.
        name (str): The report.
        enable (bool): True to switch it on.

    Raises:
        ValueError: The report is unknown.
    """
    if name not in config['StdReport'].sections or name == 'Defaults':
        raise ValueError('Unknown report.')
    config['StdReport'][name]['enable'] = 'true' if enable else 'false'


def _map_section(config):
    """Return the section holding the mapping of the active driver.

    Both drivers map WeeWX fields to names of their own.

    Returns:
        tuple[configobj.Section|None, str]: A two-way tuple (section, name of the
            subsection).
    """
    station_type = config['Station'].get('station_type')
    if station_type == 'Ecowittcustom':
        return config['Ecowittcustom'], 'sensor_map_extensions'
    if station_type == 'Rtldavis':
        return config['Rtldavis'], 'sensor_map'
    return None, ''


def read_sensors(config, columns):
    """Return what the station receives and where it goes.

    Args:
        config (configobj.ConfigObj): The configuration.
        columns (Iterable[str]): Columns of the archive.

    Returns:
        dict: observations, each with name, value and whether a column keeps
            it, and mapping, the entries of the driver's map.
    """
    known = set(columns)
    packet = status.live() or {}
    section, subsection = _map_section(config)
    mapping = dict(section.get(subsection, {})) if section is not None else {}
    return dict(
        observations=[dict(name=name, value=value, archived=name in known)
                      for name, value in sorted(packet.items())],
        map_kind=subsection, mapping=mapping,
        columns=sorted(known))


def write_mapping(config, mapping):
    """Replace the entries of the active driver's map.

    Args:
        config (configobj.ConfigObj): The configuration.
        mapping (dict): Source by target.

    Raises:
        ValueError: The driver has no map, or an entry is not valid.
    """
    section, subsection = _map_section(config)
    if section is None:
        raise ValueError('This driver has no map.')
    for left, right in mapping.items():
        if not OBSERVATION.match(str(left)) or not OBSERVATION.match(str(right)):
            raise ValueError('Names have letters, digits, dots and underscores.')
    section[subsection] = dict(mapping)
