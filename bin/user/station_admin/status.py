# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""What the status page shows."""

import json
import os
import shutil
import socket
import sqlite3
import time

import configobj

from user.station_admin import VERSION, common, i18n
from user.station_admin.i18n import N_, _

# Log messages of the drivers, as text to find and what to tell the user. The
# newest line that matches decides.
RECEPTION = (
    ('No RTL-SDR dongle found', N_('Plug in the RTL-SDR dongle.')),
    ('No permission to open the RTL-SDR dongle',
     N_('WeeWX may not open the dongle. See the log.')),
    ('The RTL-SDR dongle is in use', N_('Another program holds the dongle. See the log.')),
    ('Searching for transmitter', N_('Searching for your station. This can take a few minutes.')),
    ('Heard a Davis transmitter on channel',
     N_('Another Davis channel is on the air. Check the ISS channel.')),
    ('No Davis transmitter heard', N_('Nothing received. Check band, channel and antenna.')),
    ('Lost transmitter', N_('Reception was lost. The receiver is trying again.')),
    ('Found a Davis transmitter', N_('Station found. Waiting for it to stay in sync.')),
    ('Receiving transmitter', N_('Receiving your station.')),
    ('listen on', N_('Waiting for the first upload from your console.')),
    ('Waiting for uploads from an Ambient Weather console',
     N_('Waiting for the first upload from your console.')),
    ('Waiting for broadcasts from a WeatherFlow hub',
     N_('Waiting for the first broadcast of the hub.')),
    ('No broadcast from a WeatherFlow hub',
     N_('Nothing received. The hub must be on the same network as this station.')),
)


def reception_message(lines):
    """Say in plain words what the driver's log shows.

    Args:
        lines (list[str]): Log lines, oldest first.

    Returns:
        str|None: The message of the newest known line, or None if there is none.
    """
    for line in reversed(lines):
        # Older lines belong to the previous start, perhaps with another driver.
        if 'Initializing weewxd' in line:
            break
        for text, message in RECEPTION:
            if text in line:
                return message
    return None


def host_address():
    """Return the address other devices reach this machine at.

    Returns:
        str|None: The address, or None without a network.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connecting a UDP socket sends nothing. It only selects the route.
        probe.connect(('192.0.2.1', 9))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def last_record():
    """Return the newest archive record.

    Returns:
        dict|None: Its time and row count, or None without a database.
    """
    if not os.path.exists(common.DATABASE_PATH):
        return None
    try:
        connection = sqlite3.connect('file:%s?mode=ro' % common.DATABASE_PATH, uri=True, timeout=2)
        try:
            newest, rows = connection.execute('SELECT MAX(dateTime), COUNT(*) FROM archive').fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    return dict(time=newest, rows=rows)


def live():
    """Return the latest packet from the WeeWX service, if it is recent.

    Returns:
        dict|None: The text of each reading by name, in the units of the weather pages,
            or None if none arrived for two minutes.
    """
    try:
        with open(common.LIVE_PATH) as stream:
            packet = json.load(stream)
    except (OSError, ValueError):
        return None
    if time.time() - packet.get('written', 0) > 120:
        return None
    return packet.get('readings')


def _temperature():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as stream:
            return int(stream.read()) / 1000.0
    except (OSError, ValueError):
        return None


_labels = {}


def observation_labels(language):
    """Return the names of the observations in a language.

    The Seasons skin of WeeWX has them translated, and every station has that skin.

    Args:
        language (str): A key of i18n.LANGUAGES.

    Returns:
        dict: The name of each observation by its WeeWX name (e.g., 'outTemp'). Empty if
            the skin has no file for the language.
    """
    if language not in _labels:
        path = os.path.join(common.SKIN_ROOT, 'Seasons', 'lang', language + '.conf')
        try:
            labels = configobj.ConfigObj(path, encoding='utf-8', interpolation=False,
                                         file_error=True)['Labels']['Generic']
            _labels[language] = {name: str(text) for name, text in labels.items()
                                 if isinstance(text, str)}
        except (OSError, KeyError, configobj.ConfigObjError):
            _labels[language] = {}
    return _labels[language]


def _read(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as stream:
            return stream.read().replace('\0', '').strip()
    except OSError:
        return None


def _undervoltage():
    """Tell whether the power supply of the Raspberry Pi is too weak right now.

    Returns:
        bool|None: True if the firmware reports undervoltage, or None on a machine
            that does not report it.
    """
    # The firmware of the Raspberry Pi reports through the hwmon device rpi_volt. Its
    # alarm stays set while the voltage is too low.
    try:
        devices = os.listdir('/sys/class/hwmon')
    except OSError:
        return None
    for device in devices:
        path = os.path.join('/sys/class/hwmon', device)
        if _read(os.path.join(path, 'name')) == 'rpi_volt':
            alarm = _read(os.path.join(path, 'in0_lcrit_alarm'))
            return None if alarm is None else alarm == '1'
    return None


def _system():
    for line in (_read('/etc/os-release') or '').splitlines():
        if line.startswith('PRETTY_NAME='):
            return line.partition('=')[2].strip('"')
    return None


def raspberry(time_synced):
    """Collect what the status page shows about the Raspberry Pi.

    Args:
        time_synced (bool): Whether the clock has the time from the internet.

    Returns:
        dict: Model, system, kernel, host name, processor temperature, undervoltage,
            disk, memory, uptime, address, whether the time is synchronized, and the
            releases of the image and of this administration.
    """
    disk = shutil.disk_usage(os.path.dirname(common.DATABASE_PATH))
    return dict(model=_read('/proc/device-tree/model'), system=_system(),
                kernel=os.uname().release, hostname=socket.gethostname(),
                temperature=_temperature(), undervoltage=_undervoltage(),
                disk=dict(total=disk.total, free=disk.free), memory=_memory(),
                uptime=float(_read('/proc/uptime').split()[0]), address=host_address(),
                time_synced=time_synced, release=_read('/etc/station-release'), admin=VERSION)


def _memory():
    values = {}
    with open('/proc/meminfo') as stream:
        for line in stream:
            name, _, rest = line.partition(':')
            values[name] = int(rest.split()[0]) if rest.split() else 0
    return dict(total=values['MemTotal'] * 1024, available=values['MemAvailable'] * 1024)


def read():
    """Collect the status page.

    Returns:
        dict: What the page shows.
    """
    state = common.run(['systemctl', 'is-active', 'weewx'], 10).stdout.strip()
    enabled = common.run(['systemctl', 'is-enabled', 'weewx'], 10).stdout.strip() == 'enabled'
    synced = common.run(['timedatectl', 'show', '-p', 'NTPSynchronized', '--value'],
                        10).stdout.strip() == 'yes'
    log = common.run(['journalctl', '-u', 'weewx', '-n', '300', '-o', 'cat', '--no-pager'],
                     20).stdout.splitlines()
    readings = live()
    if not enabled:
        message = N_('Choose your station on the Station page.')
    elif not synced:
        message = N_('Waiting for the correct time from the internet. WeeWX starts after that.')
    elif state != 'active':
        message = N_('WeeWX is not running. See the log.')
    else:
        message = reception_message(log)
        # Most drivers log nothing per reading, so readings are the proof.
        if readings and (message is None or message.startswith('Waiting for the first')):
            message = N_('Receiving your station.')
        message = message or N_('Waiting for the first readings from your station.')
    names = observation_labels(i18n.current())
    labels = {name: names[name] for name in readings or {} if name in names}
    return dict(message=_(message), weewx=state, configured=enabled, record=last_record(),
                live=readings, labels=labels, log='\n'.join(log[-40:]), now=time.time(),
                raspberry=raspberry(synced))
