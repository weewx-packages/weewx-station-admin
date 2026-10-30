# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Installed extensions, the catalog, and installing from either."""

import json
import re
import time
import urllib.request

from user.station_admin import common

CATALOG_URL = 'https://raw.githubusercontent.com/weewx-packages/catalog/main/repository.json'
PACKAGE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]*$')
DEBIAN_NAME = re.compile(r'^[a-z0-9][a-z0-9+.-]+$')
CACHE_SECONDS = 3600

_catalog = dict(time=0, packages=[])


def catalog():
    """Return the packages of the catalog, read at most once an hour.

    Returns:
        list[dict]: Id, name, description, category, version and Debian packages.

    Raises:
        OSError: The catalog cannot be read and no earlier copy exists.
    """
    if time.time() - _catalog['time'] > CACHE_SECONDS or not _catalog['packages']:
        try:
            with urllib.request.urlopen(CATALOG_URL, timeout=20) as reply:
                index = json.load(reply)
        except OSError:
            if _catalog['packages']:
                return _catalog['packages']
            raise
        packages = index.get('packages', index)
        packages = packages if isinstance(packages, list) else list(packages.values())
        _catalog['packages'] = [_summary(package) for package in packages]
        _catalog['time'] = time.time()
    return _catalog['packages']


def _summary(package):
    releases = [release for release in package['releases'] if not release.get('yanked')]
    latest = releases[-1] if releases else {}
    return dict(id=package['id'], name=package.get('name', package['id']),
                description=package.get('description', ''), category=package.get('category'),
                version=latest.get('version'),
                debian=latest.get('requirements', {}).get('debian', []))


def installed():
    """Return the installed extensions, as the package manager lists them.

    Returns:
        list[dict]: Name, version, source and status.
    """
    output = common.run(common.package_command('list'), 60).stdout
    entries = []
    table = False
    for line in output.splitlines():
        if line.startswith('Installed name'):
            table = True
        elif table and line.strip():
            fields = line.split(None, 3)
            if len(fields) == 4:
                entries.append(dict(name=fields[0], version=fields[1], source=fields[2],
                                    status=fields[3]))
    return entries


def _debian_packages(package_id):
    for package in catalog():
        if package['id'] == package_id:
            names = [name for name in package['debian'] if DEBIAN_NAME.match(name)]
            return [common.privileged('apt-install', *names)] if names else []
    return []


def install_steps(package_id):
    """Return the steps that install a catalog package.

    Args:
        package_id (str): The package.

    Returns:
        list[list[str]]: The steps of the job.

    Raises:
        ValueError: The name is not valid.
    """
    if not PACKAGE_NAME.match(package_id):
        raise ValueError('Not a package name.')
    return _debian_packages(package_id) + [
        common.package_command('install', package_id, '--repo', 'packages', '--yes'),
        common.privileged('weewx-restart')]


def update_steps(package_id=None):
    """Return the steps that update one package or all of them.

    Args:
        package_id (str|None): The package, or None for all.

    Returns:
        list[list[str]]: The steps of the job.

    Raises:
        ValueError: The name is not valid.
    """
    arguments = ['update', '--yes']
    if package_id is not None:
        if not PACKAGE_NAME.match(package_id):
            raise ValueError('Not a package name.')
        arguments.insert(1, package_id)
    # The administration can be one of the updated packages. It restarts itself
    # last, because that ends this job.
    return [common.package_command(*arguments), common.privileged('weewx-restart'),
            common.privileged('admin-restart')]


def remove_steps(name):
    """Return the steps that remove an extension.

    Args:
        name (str): Its installed name.

    Returns:
        list[list[str]]: The steps of the job.

    Raises:
        ValueError: The name is not valid, or removing it would cut off this page.
    """
    if not PACKAGE_NAME.match(name):
        raise ValueError('Not a package name.')
    if name in ('station-admin', 'package-manager'):
        raise ValueError('The administration needs %s.' % name)
    return [['weectl', 'extension', 'uninstall', name, '--config=' + common.CONFIG_PATH, '-y'],
            common.privileged('weewx-restart')]


def upload_steps(path):
    """Return the steps that install an uploaded archive.

    Args:
        path (str): The stored file.

    Returns:
        list[list[str]]: The steps of the job.
    """
    return [['weectl', 'extension', 'install', path, '--config=' + common.CONFIG_PATH, '-y'],
            common.privileged('weewx-restart')]
