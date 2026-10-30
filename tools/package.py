# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Build the release archive from the files git tracks."""

import pathlib
import re
import subprocess


def build():
    """Write the archive after checking that the versions agree.

    Returns:
        pathlib.Path: The archive in dist/.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    version = re.search(r"VERSION = '([^']+)'", (root / 'install.py').read_text()).group(1)
    package = (root / 'bin/user/station_admin/__init__.py').read_text()
    if "VERSION = '%s'" % version not in package:
        raise ValueError('Installer and package versions differ')
    output = root / 'dist' / ('weewx-station-admin-%s.tar.gz' % version)
    output.parent.mkdir(exist_ok=True)
    subprocess.run(['git', 'archive', '--format=tar.gz', '--prefix=weewx-station-admin-%s/' % version,
                    '-o', str(output), 'HEAD', 'install.py', 'bin', 'LICENSE', 'README.md',
                    'CHANGELOG.md'], cwd=root, check=True)
    return output


if __name__ == '__main__':
    print(build())
