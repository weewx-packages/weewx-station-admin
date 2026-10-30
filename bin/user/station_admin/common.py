# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Paths of the station and the commands every part of the administration needs."""

import os
import subprocess

CONFIG_PATH = '/etc/weewx/weewx.conf'
USER_ROOT = '/etc/weewx/bin/user'
SKIN_ROOT = '/etc/weewx/skins'
DATABASE_PATH = '/var/lib/weewx/weewx.sdb'
STATE_DIR = '/var/lib/weewx/station-admin'
BACKUP_DIR = STATE_DIR + '/backups'
UPLOAD_DIR = STATE_DIR + '/uploads'
LIVE_PATH = '/run/weewx/live.json'
PRIVILEGED = ['sudo', '-n', '/usr/local/sbin/station-privileged']
PYTHON_PATH = '/etc/weewx/bin:/usr/share/weewx'
PACKAGES = ['python3', '-m', 'user.packages']
# Pages that run in a browser reach the service through nginx, which is the only
# place that can tell a visitor's address.
PORT = 8377


def run(command, timeout=60):
    """Run a command and return what happened, without raising.

    Args:
        command (list[str]): The command.
        timeout (int|float): Seconds to wait. Default is 60.

    Returns:
        subprocess.CompletedProcess: The result, with text output.
    """
    environment = dict(os.environ, PYTHONPATH=PYTHON_PATH)
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                              env=environment, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(command, 1, '', str(error))


def privileged(*arguments):
    """Return the command line of an action of the privileged helper.

    Args:
        arguments (str): The action and its arguments.

    Returns:
        list[str]: The command.
    """
    return PRIVILEGED + list(arguments)


def package_command(*arguments):
    """Return the command line of a package manager action for this station.

    Args:
        arguments (str): The action and its arguments.

    Returns:
        list[str]: The command.
    """
    return PACKAGES + list(arguments) + ['--config', CONFIG_PATH]
