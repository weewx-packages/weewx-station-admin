# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Backups of the station: configuration, extensions, skins and the database.

A backup holds the passwords in weewx.conf, so the files are readable only by
the account of the administration, and only a logged-in administrator can
download them.
"""

import json
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
import time

from user.station_admin import common, settings

NAME = re.compile(r'^[A-Za-z0-9._-]+\.tar\.gz$')


def _path(name):
    if not NAME.match(name) or '..' in name:
        raise ValueError('Not a backup name.')
    return os.path.join(common.BACKUP_DIR, name)


def path_of(name):
    """Return the path of a backup that exists.

    Args:
        name (str): The file name.

    Returns:
        str: The path.

    Raises:
        ValueError: No such backup.
    """
    path = _path(name)
    if not os.path.exists(path):
        raise ValueError('No such backup.')
    return path


def listing():
    """Return the stored backups, newest first.

    Returns:
        list[dict]: Name, size and time of each.
    """
    if not os.path.isdir(common.BACKUP_DIR):
        return []
    entries = []
    for name in os.listdir(common.BACKUP_DIR):
        if NAME.match(name):
            status = os.stat(os.path.join(common.BACKUP_DIR, name))
            entries.append(dict(name=name, size=status.st_size, time=status.st_mtime))
    return sorted(entries, key=lambda entry: -entry['time'])


def remove(name):
    """Delete a backup.

    Args:
        name (str): The file name.
    """
    os.remove(path_of(name))


def create_step(job):
    """Write a backup. WeeWX can keep running: SQLite copies a consistent state.

    Args:
        job (jobs.Job): Receives the progress.
    """
    os.makedirs(common.BACKUP_DIR, mode=0o700, exist_ok=True)
    size = os.path.getsize(common.DATABASE_PATH) if os.path.exists(common.DATABASE_PATH) else 0
    if shutil.disk_usage(common.BACKUP_DIR).free < 2 * size + 50 * 1024 * 1024:
        raise RuntimeError('Not enough free space for a backup.')
    stamp = time.strftime('%Y%m%d-%H%M%S')
    name = 'station-%s.tar.gz' % stamp
    with tempfile.TemporaryDirectory(dir=common.BACKUP_DIR) as work:
        copy = os.path.join(work, 'weewx.sdb')
        if size:
            job.write('Copying the database.')
            source = sqlite3.connect('file:%s?mode=ro' % common.DATABASE_PATH, uri=True)
            target = sqlite3.connect(copy)
            try:
                with target:
                    source.backup(target)
            finally:
                source.close()
                target.close()
        job.write('Packing %s.' % name)
        temporary = os.path.join(work, name)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(descriptor)
        with tarfile.open(temporary, 'w:gz') as archive:
            manifest = os.path.join(work, 'MANIFEST.json')
            with open(manifest, 'w') as stream:
                json.dump(dict(format=1, created=time.time()), stream)
            archive.add(manifest, 'MANIFEST.json')
            archive.add(common.CONFIG_PATH, 'weewx.conf')
            archive.add(common.USER_ROOT, 'bin/user',
                        filter=lambda info: None if '__pycache__' in info.name else info)
            archive.add(common.SKIN_ROOT, 'skins')
            if size:
                archive.add(copy, 'weewx.sdb')
        os.replace(temporary, _path(name))
    job.write('Backup %s is ready.' % name)


def restore_step(name):
    """Return the step that restores a backup over the stopped station.

    Args:
        name (str): The file name.

    Returns:
        Callable[[jobs.Job], None]: The step, called as step(job).
    """
    path = path_of(name)

    def restore(job):
        with tempfile.TemporaryDirectory(dir=common.STATE_DIR) as work:
            with tarfile.open(path, 'r:gz') as archive:
                # The data filter refuses absolute paths and links leaving the
                # directory, so an uploaded archive cannot write elsewhere.
                archive.extractall(work, filter='data')
            if not os.path.exists(os.path.join(work, 'MANIFEST.json')):
                raise RuntimeError('This is not a backup of a station.')
            settings.load(os.path.join(work, 'weewx.conf'))
            job.write('Restoring the configuration.')
            shutil.copyfile(os.path.join(work, 'weewx.conf'), common.CONFIG_PATH)
            job.write('Restoring extensions and skins.')
            shutil.copytree(os.path.join(work, 'bin/user'), common.USER_ROOT, dirs_exist_ok=True)
            shutil.copytree(os.path.join(work, 'skins'), common.SKIN_ROOT, dirs_exist_ok=True)
            database = os.path.join(work, 'weewx.sdb')
            if os.path.exists(database):
                job.write('Restoring the database.')
                shutil.copyfile(database, common.DATABASE_PATH)
        job.write('Restored %s.' % name)

    return restore
