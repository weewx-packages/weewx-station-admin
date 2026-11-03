# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Inspect and extend the archive table."""

import os
import re
import sqlite3

from user.station_admin import backups, common
from user.station_admin.i18n import _

NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
TYPES = ('REAL', 'INTEGER', 'TEXT')
# WeeWX cannot run without these.
PROTECTED = ('dateTime', 'usUnits', 'interval')


def columns():
    """Return the columns of the archive and how many rows hold a value.

    Returns:
        dict: columns, a list of dicts with name, type and protected, and
            size, the file size in bytes. Empty without a database.
    """
    if not os.path.exists(common.DATABASE_PATH):
        return dict(columns=[], size=0)
    connection = sqlite3.connect('file:%s?mode=ro' % common.DATABASE_PATH, uri=True, timeout=5)
    try:
        rows = connection.execute('PRAGMA table_info(archive)').fetchall()
    finally:
        connection.close()
    return dict(size=os.path.getsize(common.DATABASE_PATH),
                columns=[dict(name=row[1], type=row[2], protected=row[1] in PROTECTED)
                         for row in rows])


def change_steps(action, form):
    """Return the job that changes the schema, or raise if the request is not valid.

    Args:
        action (str): 'add', 'rename' or 'drop'.
        form (dict): name, and type for add, new_name for rename.

    Returns:
        tuple[str, list, list]: A three-way tuple (title, steps, cleanup) for
            jobs.start. WeeWX stops for the change, and a backup comes first.

    Raises:
        ValueError: The request is not valid.
    """
    name = str(form.get('name', ''))
    if not NAME.match(name):
        raise ValueError(_('A column name has letters, digits and underscores.'))
    existing = [column['name'] for column in columns()['columns']]
    weectl = ['weectl', 'database']
    tail = ['--config=' + common.CONFIG_PATH, '-y']
    if action == 'add':
        kind = form.get('type', 'REAL')
        if kind not in TYPES:
            raise ValueError(_('The type must be REAL, INTEGER or TEXT.'))
        if name in existing:
            raise ValueError(_('The column {name} exists already.', name=name))
        command = weectl + ['add-column', name, '--type=' + kind] + tail
        title = _('Add column {name}', name=name)
    elif action in ('rename', 'drop'):
        if name not in existing:
            raise ValueError(_('The column {name} does not exist.', name=name))
        if name in PROTECTED:
            raise ValueError(_('WeeWX needs the column {name}.', name=name))
        if action == 'rename':
            new_name = str(form.get('new_name', ''))
            if not NAME.match(new_name) or new_name in existing:
                raise ValueError(_('Choose a new name that is not in use.'))
            command = weectl + ['rename-column', name, new_name] + tail
            title = _('Rename column {name} to {new_name}', name=name, new_name=new_name)
        else:
            command = weectl + ['drop-columns', name] + tail
            title = _('Drop column {name}', name=name)
    else:
        raise ValueError(_('Unknown action.'))
    steps = [backups.create_step, common.privileged('weewx-stop'), command]
    return title, steps, [common.privileged('weewx-start')]
