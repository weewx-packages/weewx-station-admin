# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Read and change weewx.conf."""

import os
import shutil
import tempfile
import zoneinfo

import configobj

from user.station_admin import common, jobs

UNITS = ('metricwx', 'metric', 'us')
DRIVERS = {
    'rtldavis': dict(module='user.rtldavis', section='Rtldavis', title='Davis, through an RTL-SDR dongle'),
    'ecowitt': dict(module='user.ecowittcustom', section='Ecowittcustom', title='Ecowitt console'),
}


def load(path=None):
    """Read weewx.conf.

    Args:
        path (str|None): The file. Default is the station's.

    Returns:
        configobj.ConfigObj: The configuration, comments included.
    """
    return configobj.ConfigObj(path or common.CONFIG_PATH, encoding='utf-8', interpolation=False,
                               file_error=True)


def save(config):
    """Replace weewx.conf in one step, so a crash cannot leave half a file.

    Args:
        config (configobj.ConfigObj): The configuration.
    """
    directory = os.path.dirname(config.filename)
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix='.weewx.conf.')
    os.close(descriptor)
    with open(temporary, 'wb') as stream:
        config.write(stream)
    os.chmod(temporary, 0o660)
    os.replace(temporary, config.filename)


def _number(form, name, low, high, errors):
    try:
        value = float(str(form.get(name, '')).strip().replace(',', '.'))
    except ValueError:
        errors.append('%s must be a number.' % name.capitalize())
        return None
    # The comparison also rejects nan, which float() accepts.
    if not low <= value <= high:
        errors.append('%s must be between %g and %g.' % (name.capitalize(), low, high))
        return None
    return value


def parse_station(form):
    """Validate the settings of the station page.

    Args:
        form (dict): Submitted values.

    Returns:
        tuple[dict, list[str]]: A two-way tuple (settings, errors). The settings are
            usable only if errors is empty.
    """
    errors = []
    settings = dict(location=str(form.get('location', '')).strip(),
                    timezone=str(form.get('timezone', '')).strip(),
                    units=form.get('units'), driver=form.get('driver'),
                    altitude_unit=form.get('altitude_unit'))
    settings['latitude'] = _number(form, 'latitude', -90, 90, errors)
    settings['longitude'] = _number(form, 'longitude', -180, 180, errors)
    settings['altitude'] = _number(form, 'altitude', -500, 30000, errors)
    if not settings['location'] or not settings['location'].isprintable():
        errors.append('The station needs a name.')
    if settings['timezone'] not in zoneinfo.available_timezones():
        errors.append('Time zone must be a name such as Europe/Berlin.')
    if settings['units'] not in UNITS:
        errors.append('Choose the units.')
    if settings['altitude_unit'] not in ('meter', 'foot'):
        errors.append('Choose the unit of the altitude.')
    if settings['driver'] not in DRIVERS:
        errors.append('Choose the kind of station.')
    elif settings['driver'] == 'rtldavis':
        settings['band'] = form.get('band')
        settings['channel'] = str(form.get('channel'))
        settings['bucket'] = str(form.get('bucket'))
        if settings['band'] not in ('EU', 'US', 'NZ'):
            errors.append('Choose the frequency band.')
        if settings['channel'] not in '12345678' or len(settings['channel']) != 1:
            errors.append('The ISS channel must be 1 to 8.')
        if settings['bucket'] not in ('0', '1'):
            errors.append('Choose the rain bucket.')
    else:
        settings['port'] = _number(form, 'port', 1024, 65535, errors)
    return settings, errors


def read_station(config):
    """Return the values of the station page.

    Args:
        config (configobj.ConfigObj): The configuration.

    Returns:
        dict: Current values.
    """
    station = config['Station']
    altitude = station.get('altitude', ['0', 'meter'])
    rtldavis = config.get('Rtldavis', {})
    ecowitt = config.get('Ecowittcustom', {})
    driver = 'ecowitt' if station.get('station_type') == 'Ecowittcustom' else 'rtldavis'
    return dict(location=station.get('location', ''), latitude=station.get('latitude', ''),
                longitude=station.get('longitude', ''), altitude=altitude[0],
                altitude_unit=altitude[1],
                units=config['StdReport']['Defaults'].get('unit_system', 'metricwx'),
                driver=driver, band=rtldavis.get('transceiver_frequency', 'EU'),
                channel=rtldavis.get('iss_channel', '1'),
                bucket=rtldavis.get('rain_bucket_type', '1'),
                port=ecowitt.get('port', '8080'))


def station_steps(settings):
    """Return the steps that apply the settings and start WeeWX.

    Args:
        settings (dict): Settings from parse_station.

    Returns:
        list[list[str]|Callable[[jobs.Job], None]]: The steps of the job.
    """
    driver = DRIVERS[settings['driver']]

    def write_driver(job):
        # weectl has no options for driver settings. ConfigObj keeps the comments.
        config = load()
        section = config[driver['section']]
        if settings['driver'] == 'rtldavis':
            section['transceiver_frequency'] = settings['band']
            section['iss_channel'] = settings['channel']
            section['rain_bucket_type'] = settings['bucket']
        else:
            section['port'] = str(int(settings['port']))
        save(config)
        job.write('Saved the settings of the %s driver.' % settings['driver'])

    return [
        ['weectl', 'station', 'reconfigure', '--config=' + common.CONFIG_PATH, '--no-prompt',
         '--no-backup', '--driver=' + driver['module'],
         '--location=' + settings['location'],
         '--latitude=%s' % settings['latitude'],
         '--longitude=%s' % settings['longitude'],
         '--altitude=%s,%s' % (settings['altitude'], settings['altitude_unit']),
         '--units=' + settings['units']],
        write_driver,
        common.privileged('set-timezone', settings['timezone']),
        common.privileged('weewx-enable'),
        common.privileged('weewx-restart'),
    ]


def read_text():
    """Return weewx.conf as text.

    Returns:
        str: The file.
    """
    with open(common.CONFIG_PATH, encoding='utf-8') as stream:
        return stream.read()


def write_text(text):
    """Replace weewx.conf after checking that it parses, keeping one earlier copy.

    Args:
        text (str): The new file.

    Raises:
        ValueError: The text is no valid configuration.
    """
    try:
        parsed = configobj.ConfigObj(text.splitlines(), encoding='utf-8', interpolation=False)
    except configobj.ConfigObjError as error:
        raise ValueError('The file is not valid: %s' % error)
    if 'Station' not in parsed or 'Engine' not in parsed:
        raise ValueError('The file has no [Station] or [Engine] section.')
    directory = os.path.dirname(common.CONFIG_PATH)
    shutil.copy2(common.CONFIG_PATH, common.CONFIG_PATH + '.previous')
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix='.weewx.conf.')
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(text)
    os.chmod(temporary, 0o660)
    os.replace(temporary, common.CONFIG_PATH)
