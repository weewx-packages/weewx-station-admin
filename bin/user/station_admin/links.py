# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Install an extension from a link, with the installer of WeeWX.

`weectl extension install` takes a file or a URL, but only a URL whose server names the
file, which many do not. So this module turns the link someone pastes into an archive,
downloads it and hands the file to weectl.
"""

import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from user.station_admin import common, jobs
from user.station_admin.i18n import _

ARCHIVE = re.compile(r'\.(zip|tar\.gz|tgz|tar\.bz2|tar\.xz|tar)$', re.IGNORECASE)
GITHUB = re.compile(r'^https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/(.*))?$')
# The short form owner/repo names a repository on GitHub.
SHORT = re.compile(r'^([\w.-]+)/([\w.-]+)$')
CATALOG_PAGE = re.compile(
    r'^https?://github\.com/weewx-packages/catalog/blob/[^/]+/packages/([a-z0-9-]+)\.md$')
MAX_BYTES = 100 * 1024 * 1024
TIMEOUT = 60
HEADERS = {'User-Agent': 'weewx-station-admin', 'Accept': 'application/vnd.github+json'}


def _clean(link):
    link = str(link).strip()
    parts = urllib.parse.urlsplit(link)
    if parts.scheme in ('http', 'https'):
        # Fragments and queries such as ?tab=readme name a view, not a version.
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), '', ''))
    return link.rstrip('/')


def _repository(link):
    """Return the GitHub repository a link names, and the rest of its path.

    Args:
        link (str): The cleaned link.

    Returns:
        tuple[str, str, str]|None: A three-way tuple (owner, repository, rest), or None
            if the link names no repository on GitHub.
    """
    match = GITHUB.match(link) or SHORT.match(link)
    if not match:
        return None
    owner, name = match.group(1), match.group(2)
    rest = match.group(3) if match.re is GITHUB else None
    return owner, name, rest or ''


def catalog_package(link, packages):
    """Return the catalog package a link stands for.

    A package from a catalog gets updates there, so a link to the page of a package, or
    to the repository a package names as its home, installs from the catalog.

    Args:
        link (str): The link.
        packages (list[dict]): The packages of the catalogs, each with id, repo and
            homepage.

    Returns:
        dict|None: The package, or None if the link stands for no package.
    """
    link = _clean(link)
    page = CATALOG_PAGE.match(link)
    if page:
        return next((package for package in packages if package['id'] == page.group(1)
                     and package['repo'] == 'packages'), None)
    named = _repository(link)
    # A link to one release or branch asks for that version, not for the newest.
    if named is None or named[2] not in ('', 'releases', 'releases/latest'):
        return None
    for package in packages:
        home = _repository(_clean(package.get('homepage') or ''))
        if home and (home[0].lower(), home[1].lower()) == (
                named[0].lower(), named[1].lower()):
            return package
    return None


def _github(path):
    """Ask the GitHub API.

    Args:
        path (str): The path after https://api.github.com/.

    Returns:
        dict|None: The answer, or None if GitHub does not know the thing.

    Raises:
        ValueError: GitHub refuses, or cannot be reached.
    """
    request = urllib.request.Request('https://api.github.com/' + path, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
            return json.load(reply)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        if error.code in (403, 429):
            raise ValueError(_('GitHub allows no more requests right now. Try again in an hour.'))
        raise ValueError(_('GitHub answered with error {code}.', code=error.code))
    except OSError as error:
        raise ValueError(_('GitHub cannot be reached: {error}', error=error))


def _from_release(owner, name, release):
    # An installer archive attached to the release is what its author ships. Without
    # one, the source of the tagged commit is the release.
    for asset in release.get('assets', []):
        if ARCHIVE.search(asset.get('name', '')):
            return asset['browser_download_url'], _('release {tag}, file {file}',
                                                    tag=release['tag_name'], file=asset['name'])
    return ('https://github.com/%s/%s/archive/refs/tags/%s.tar.gz'
            % (owner, name, urllib.parse.quote(release['tag_name'])),
            _('release {tag}', tag=release['tag_name']))


def archive_url(link):
    """Find the archive a link stands for.

    Args:
        link (str): A link to an archive, or to a GitHub repository, one of its
            releases or one of its branches. owner/repo stands for a repository on
            GitHub.

    Returns:
        tuple[str, str]: A two-way tuple (url, description). The description says
            which version the archive holds.

    Raises:
        ValueError: The link stands for no archive.
    """
    link = _clean(link)
    path = urllib.parse.urlsplit(link).path
    if link.startswith(('http://', 'https://')) and ARCHIVE.search(path):
        return link, _('the archive at this link')
    named = _repository(link)
    if named is None:
        raise ValueError(_('Use a link to a GitHub repository, to one of its releases, or to '
                           'a .zip or .tar.gz file.'))
    owner, name, rest = named
    if rest in ('', 'releases', 'releases/latest'):
        # GitHub's latest release leaves out prereleases. An extension that has only
        # prereleases still ships those rather than its branch.
        release = _github('repos/%s/%s/releases/latest' % (owner, name)) or next(
            iter(_github('repos/%s/%s/releases?per_page=1' % (owner, name)) or []), None)
        if release:
            return _from_release(owner, name, release)
        # Many extensions publish no releases, only their main branch.
        repository = _github('repos/%s/%s' % (owner, name))
        if repository is None:
            raise ValueError(_('GitHub has no repository {owner}/{name}.', owner=owner, name=name))
        branch = repository['default_branch']
        return ('https://github.com/%s/%s/archive/refs/heads/%s.tar.gz' % (owner, name, branch),
                _('branch {branch}, as it is now', branch=branch))
    if rest.startswith('releases/tag/'):
        tag = urllib.parse.unquote(rest[len('releases/tag/'):])
        release = _github('repos/%s/%s/releases/tags/%s' % (owner, name, urllib.parse.quote(tag)))
        if release:
            return _from_release(owner, name, release)
        return ('https://github.com/%s/%s/archive/refs/tags/%s.tar.gz' % (owner, name, tag),
                _('tag {tag}', tag=tag))
    if rest.startswith('tree/'):
        reference = rest[len('tree/'):]
        return ('https://github.com/%s/%s/archive/%s.tar.gz' % (owner, name, reference),
                _('{reference}, as it is now', reference=reference))
    raise ValueError(_('Use a link to a GitHub repository, to one of its releases, or to '
                       'a .zip or .tar.gz file.'))


def download(url, directory):
    """Download an archive.

    Args:
        url (str): Its address.
        directory (str): Where to store it.

    Returns:
        str: The path of the file. Its name ends in .zip or .tar.gz, which tells weectl
            how to open it.

    Raises:
        ValueError: The download fails or is too large.
    """
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = os.path.join(directory, uuid.uuid4().hex)
    request = urllib.request.Request(url, headers={'User-Agent': HEADERS['User-Agent']})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as reply, \
                open(path, 'wb') as stream:
            size = 0
            while True:
                block = reply.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > MAX_BYTES:
                    raise ValueError(_('The download is larger than {size} MB.',
                                       size=MAX_BYTES // (1024 * 1024)))
                stream.write(block)
    except (OSError, ValueError) as error:
        if os.path.exists(path):
            os.remove(path)
        if isinstance(error, ValueError):
            raise
        raise ValueError(_('The download failed: {error}', error=error))
    named = path + ('.zip' if zipfile.is_zipfile(path) else '.tar.gz')
    shutil.move(path, named)
    return named


def install_step(link):
    """Return the step of a job that installs the extension a link stands for.

    Args:
        link (str): The link.

    Returns:
        Callable[[jobs.Job], None]: Called as step(job). Finds and downloads the archive,
            then runs `weectl extension install` on it.
    """
    def install(job):
        url, description = archive_url(link)
        job.write(_('Installing {description}: {url}', description=description, url=url))
        path = download(url, common.UPLOAD_DIR)
        try:
            jobs.run_command(job, ['weectl', 'extension', 'install', path,
                                   '--config=' + common.CONFIG_PATH, '-y'])
        finally:
            os.remove(path)

    return install
