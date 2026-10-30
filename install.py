# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Installer of the station administration."""

import os

from weecfg.extension import ExtensionInstaller

VERSION = '0.1.0a1'


def loader():
    return StationAdminInstaller()


class StationAdminInstaller(ExtensionInstaller):
    def __init__(self):
        package = 'bin/user/station_admin'
        super(StationAdminInstaller, self).__init__(
            version=VERSION,
            name='station-admin',
            description='Web administration of a WeeWX station.',
            author='Manuel Hilgert',
            author_email='hilman2@gmail.com',
            report_services='user.station_admin.live.StationLive',
            files=[(package, [os.path.join(package, name) for name in (
                       '__init__.py', '__main__.py', 'auth.py', 'backups.py', 'common.py',
                       'database.py', 'extensions.py', 'jobs.py', 'live.py', 'server.py',
                       'services.py', 'settings.py', 'status.py')]),
                   (package + '/ui', [os.path.join(package, 'ui', name) for name in (
                       'app.js', 'index.html', 'style.css')])])
