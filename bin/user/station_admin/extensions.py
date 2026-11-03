# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Installed extensions, the catalog, and installing from either."""

import json
import re
import time
import urllib.request

import configobj

from user.station_admin import common
from user.station_admin.i18n import _

PACKAGE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]*$')
DEBIAN_NAME = re.compile(r'^[a-z0-9][a-z0-9+.-]+$')
# The aliases the package manager accepts for a catalog.
ALIAS = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
CACHE_SECONDS = 3600
# The catalog the image registers. The station page installs its drivers from there.
MAIN = 'packages'

# The packages of each catalog by its URL, with the time they were read.
_indexes = {}


def repositories(config):
    """Return the catalogs the package manager knows.

    Args:
        config (configobj.ConfigObj): The configuration.

    Returns:
        list[dict]: Alias, URL and whether it is enabled, as [ExtensionRepositories]
            holds them, and whether it is the main catalog, which stays.
    """
    section = config.get('ExtensionRepositories', {})
    return [dict(alias=alias, url=section[alias].get('url', ''), main=alias == MAIN,
                 enabled=str(section[alias].get('enabled', 'true')).lower() == 'true')
            for alias in getattr(section, 'sections', [])]


def _index(url):
    """Return the packages of one catalog, read at most once an hour.

    Args:
        url (str): The URL of its repository.json.

    Returns:
        list[dict]: Id, name, description, category, version, Debian packages and
            homepage.

    Raises:
        OSError: The catalog cannot be read and no earlier copy exists.
    """
    cached = _indexes.get(url)
    if cached and time.time() - cached['time'] < CACHE_SECONDS:
        return cached['packages']
    try:
        with urllib.request.urlopen(url, timeout=20) as reply:
            index = json.load(reply)
    except (OSError, ValueError) as error:
        if cached:
            return cached['packages']
        raise OSError(str(error))
    packages = index.get('packages', index)
    packages = packages if isinstance(packages, list) else list(packages.values())
    _indexes[url] = dict(time=time.time(), packages=[_summary(package) for package in packages])
    return _indexes[url]['packages']


def catalog(config):
    """Return the packages of every enabled catalog.

    Args:
        config (configobj.ConfigObj): The configuration.

    Returns:
        tuple[list[dict], list[str]]: A two-way tuple (packages, errors). Each package
            has the alias of its catalog as repo. Each error names a catalog that
            cannot be read.
    """
    packages, errors = [], []
    for source in repositories(config):
        if not source['enabled']:
            continue
        try:
            packages.extend(dict(package, repo=source['alias'])
                            for package in _index(source['url']))
        except OSError as error:
            errors.append(_('The catalog {alias} cannot be read: {error}',
                            alias=source['alias'], error=error))
    return packages, errors


def _summary(package):
    releases = [release for release in package['releases'] if not release.get('yanked')]
    latest = releases[-1] if releases else {}
    return dict(id=package['id'], name=package.get('name', package['id']),
                description=package.get('description', ''), category=package.get('category'),
                version=latest.get('version'), homepage=package.get('homepage', ''),
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


def _debian_packages(package_id, repo):
    config = configobj.ConfigObj(common.CONFIG_PATH, encoding='utf-8', interpolation=False)
    url = next((source['url'] for source in repositories(config) if source['alias'] == repo), None)
    for package in _index(url) if url else []:
        if package['id'] == package_id:
            names = [name for name in package['debian'] if DEBIAN_NAME.match(name)]
            return [common.privileged('apt-install', *names)] if names else []
    return []


def package_steps(package_id, pre=False, repo=MAIN):
    """Return the steps that install a catalog package, without restarting WeeWX.

    Args:
        package_id (str): The package.
        pre (bool): True to allow a prerelease. Default is False.
        repo (str): The alias of the catalog. Default is the catalog of the image.

    Returns:
        list[list[str]]: The steps of the job.

    Raises:
        ValueError: The name is not valid.
        OSError: The package needs the catalog, and it cannot be read.
    """
    if not PACKAGE_NAME.match(package_id):
        raise ValueError(_('Not a package name.'))
    if not ALIAS.match(repo):
        raise ValueError(_('Not a catalog name.'))
    command = ['install', package_id, '--repo', repo, '--yes']
    return _debian_packages(package_id, repo) + [
        common.package_command(*command + ['--pre'] if pre else command)]


def install_steps(package_id, repo=MAIN):
    """Return the steps that install a catalog package and restart WeeWX.

    Args:
        package_id (str): The package.
        repo (str): The alias of the catalog. Default is the catalog of the image.

    Returns:
        list[list[str]]: The steps of the job.

    Raises:
        ValueError: The name is not valid.
    """
    return package_steps(package_id, repo=repo) + [common.privileged('weewx-restart')]


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
            raise ValueError(_('Not a package name.'))
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
        raise ValueError(_('Not a package name.'))
    if name in ('station-admin', 'package-manager'):
        raise ValueError(_('The administration needs {name}.', name=name))
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


def repository_steps(action, alias, url=None):
    """Return the steps that add, enable, disable or remove a catalog.

    Args:
        action (str): 'add', 'enable', 'disable' or 'remove'.
        alias (str): The name of the catalog on this station.
        url (str|None): The URL of its repository.json, for 'add'.

    Returns:
        list[list[str]]: The steps of the job.

    Raises:
        ValueError: The action, the name or the URL is not valid.
    """
    if not ALIAS.match(alias or '') or len(alias) > 64:
        raise ValueError(_('A catalog name has small letters, digits and single dashes.'))
    if action == 'add':
        if not str(url or '').startswith('https://'):
            raise ValueError(_('The address of a catalog starts with https://.'))
        return [common.package_command('repo', 'add', alias, url, '--yes')]
    if action in ('enable', 'disable', 'remove'):
        if action != 'enable' and alias == MAIN:
            raise ValueError(_('The station installs its drivers from the catalog {alias}.',
                               alias=MAIN))
        return [common.package_command('repo', action, alias, '--yes')]
    raise ValueError(_('Unknown action.'))
