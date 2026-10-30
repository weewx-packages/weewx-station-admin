# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""What the status page shows."""

import json
import os
import shutil
import socket
import sqlite3
import time

from user.station_admin import common

# Log messages of the drivers, as text to find and what to tell the user. The
# newest line that matches decides.
RECEPTION = (
    ('No RTL-SDR dongle found', 'Plug in the RTL-SDR dongle.'),
    ('No permission to open the RTL-SDR dongle', 'WeeWX may not open the dongle. See the log.'),
    ('The RTL-SDR dongle is in use', 'Another program holds the dongle. See the log.'),
    ('Searching for transmitter', 'Searching for your station. This can take a few minutes.'),
    ('Heard a Davis transmitter on channel', 'Another Davis channel is on the air. Check the ISS channel.'),
    ('No Davis transmitter heard', 'Nothing received. Check band, channel and antenna.'),
    ('Lost transmitter', 'Reception was lost. The receiver is trying again.'),
    ('Found a Davis transmitter', 'Station found. Waiting for it to stay in sync.'),
    ('Receiving transmitter', 'Receiving your station.'),
    ('listen on', 'Waiting for the first upload from your console.'),
)


def reception_message(lines):
    """Say in plain words what the driver's log shows.

    Args:
        lines (list[str]): Log lines, oldest first.

    Returns:
        str|None: The message of the newest known line, or None if there is none.
    """
    for line in reversed(lines):
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
        dict|None: Observations by name, or None if none arrived for two minutes.
    """
    try:
        with open(common.LIVE_PATH) as stream:
            packet = json.load(stream)
    except (OSError, ValueError):
        return None
    if time.time() - packet.get('written', 0) > 120:
        return None
    return packet.get('observations')


def _temperature():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as stream:
            return int(stream.read()) / 1000.0
    except (OSError, ValueError):
        return None


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
    if not enabled:
        message = 'Choose your station on the Station page.'
    elif not synced:
        message = 'Waiting for the correct time from the internet. WeeWX starts after that.'
    elif state != 'active':
        message = 'WeeWX is not running. See the log.'
    else:
        message = reception_message(log)
        # The Ecowitt driver logs nothing per upload, so readings are the proof.
        if live() and (message is None or message.startswith('Waiting for the first upload')):
            message = 'Receiving your console.'
        message = message or 'WeeWX is starting.'
    disk = shutil.disk_usage(os.path.dirname(common.DATABASE_PATH))
    try:
        with open('/etc/station-release') as stream:
            release = stream.read().strip()
    except OSError:
        release = None
    return dict(message=message, weewx=state, configured=enabled, time_synced=synced,
                record=last_record(), live=live(), log='\n'.join(log[-40:]),
                address=host_address(), now=time.time(),
                disk=dict(total=disk.total, free=disk.free), memory=_memory(),
                temperature=_temperature(), release=release,
                uptime=float(open('/proc/uptime').read().split()[0]))
