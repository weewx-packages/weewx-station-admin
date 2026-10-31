# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Smoke tests of the administration, against a temporary station."""

import http.client
import http.server
import json
import os
import sqlite3
import subprocess
import tarfile
import threading

import pytest

from user.station_admin import auth, backups, common, database, jobs, server, services, settings, status

CONFIG = """
[Station]
    location = Test
    latitude = 0
    longitude = 0
    altitude = 0, meter
    station_type = Ecowittcustom

[Ecowittcustom]
    driver = user.ecowittcustom
    port = 8080

[StdRESTful]
    [[Wunderground]]
        enable = false
        station = replace_me
        password = replace_me

[StdReport]
    [[Belchertown]]
        skin = Belchertown
        enable = true
    [[Defaults]]
        unit_system = metricwx

[Engine]
    [[Services]]
        report_services = weewx.engine.StdPrint
"""


@pytest.fixture
def station(tmp_path, monkeypatch):
    root = tmp_path / 'etc'
    (root / 'bin/user').mkdir(parents=True)
    (root / 'skins').mkdir()
    (root / 'weewx.conf').write_text(CONFIG)
    (root / 'bin/user/extra.py').write_text('# extension\n')
    state = tmp_path / 'state'
    database_path = tmp_path / 'weewx.sdb'
    connection = sqlite3.connect(database_path)
    connection.execute('CREATE TABLE archive (dateTime INTEGER, usUnits INTEGER, '
                       '"interval" INTEGER, outTemp REAL)')
    connection.execute('INSERT INTO archive VALUES (100, 1, 5, 21.5)')
    connection.commit()
    connection.close()
    monkeypatch.setattr(common, 'CONFIG_PATH', str(root / 'weewx.conf'))
    monkeypatch.setattr(common, 'USER_ROOT', str(root / 'bin/user'))
    monkeypatch.setattr(common, 'SKIN_ROOT', str(root / 'skins'))
    monkeypatch.setattr(common, 'DATABASE_PATH', str(database_path))
    monkeypatch.setattr(common, 'STATE_DIR', str(state))
    monkeypatch.setattr(common, 'BACKUP_DIR', str(state / 'backups'))
    monkeypatch.setattr(common, 'UPLOAD_DIR', str(state / 'uploads'))
    state.mkdir()
    return tmp_path


class Log:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)


def test_password_and_guess_limit(station):
    assert not auth.has_password()
    with pytest.raises(ValueError):
        auth.set_password('short')
    auth.set_password('correct horse')
    assert auth.check_password('correct horse')
    assert os.stat(auth._password_path()).st_mode & 0o777 == 0o600
    auth._failures.clear()
    for _ in range(5):
        assert not auth.check_password('wrong')
    assert not auth.check_password('correct horse')
    auth._failures.clear()


def test_station_form_is_validated(monkeypatch):
    listing = 'C\nC.utf8\nPOSIX\nde_DE.utf8\nen_GB.utf8\nxx_YY.utf8\nxx_YY.iso88591\n'
    monkeypatch.setattr(settings.common, 'run',
                        lambda command, timeout: subprocess.CompletedProcess(command, 0, listing))
    assert settings.installed_languages() == {'de_DE.UTF-8': 'Deutsch (Deutschland)',
                                              'en_GB.UTF-8': 'English (United Kingdom)',
                                              'xx_YY.UTF-8': 'xx_YY'}
    good = dict(location='Garden', latitude='52,5', longitude='13.4', altitude='34',
                altitude_unit='meter', timezone='Europe/Berlin', units='metricwx',
                driver='ecowitt', port='8080', language='de_DE.UTF-8')
    settings_, errors = settings.parse_station(good)
    assert errors == [] and settings_['latitude'] == 52.5
    _, errors = settings.parse_station(dict(good, latitude='nan', driver='x', timezone='Mars'))
    assert len(errors) == 3
    _, errors = settings.parse_station(dict(good, language='fr_FR.UTF-8'))
    assert errors == ['Choose the language.']
    _, errors = settings.parse_station(dict(good, driver='rtldavis', band='EU', channel='12',
                                            bucket='1'))
    assert errors == ['The ISS channel must be 1 to 8.']


def test_language_sets_both_options_of_belchertown(station):
    assert settings.read_station(settings.load())['language'] == settings.DEFAULT_LANGUAGE
    steps = settings.station_steps(dict(location='Garden', latitude=52.5, longitude=13.4,
                                        altitude=34.0, altitude_unit='meter', units='metricwx',
                                        timezone='Europe/Berlin', driver='ecowitt', port=8080.0,
                                        language='de_DE.UTF-8'))
    for step in steps:
        if callable(step):
            step(Log())
    config = settings.load()
    assert config['StdReport']['Belchertown']['lang'] == 'de_DE.UTF-8'
    assert config['StdReport']['Belchertown']['Extras']['belchertown_locale'] == 'de_DE.UTF-8'
    assert settings.read_station(config)['language'] == 'de_DE.UTF-8'


def test_backup_holds_a_consistent_database_and_restores(station):
    backups.create_step(Log())
    name = backups.listing()[0]['name']
    with tarfile.open(backups.path_of(name)) as archive:
        names = archive.getnames()
    assert {'MANIFEST.json', 'weewx.conf', 'weewx.sdb', 'bin/user/extra.py'} <= set(names)
    assert os.stat(backups.path_of(name)).st_mode & 0o077 == 0

    connection = sqlite3.connect(common.DATABASE_PATH)
    connection.execute('DELETE FROM archive')
    connection.commit()
    connection.close()
    backups.restore_step(name)(Log())
    connection = sqlite3.connect(common.DATABASE_PATH)
    assert connection.execute('SELECT outTemp FROM archive').fetchall() == [(21.5,)]
    connection.close()


def test_backup_names_stay_in_their_directory(station):
    for name in ('../weewx.conf', '../../x.tar.gz', 'a/b.tar.gz'):
        with pytest.raises(ValueError):
            backups.path_of(name)


def test_schema_changes_protect_what_weewx_needs(station):
    with pytest.raises(ValueError):
        database.change_steps('drop', dict(name='dateTime'))
    with pytest.raises(ValueError):
        database.change_steps('add', dict(name='bad name; DROP'))
    with pytest.raises(ValueError):
        database.change_steps('add', dict(name='outTemp'))
    title, steps, cleanup = database.change_steps('add', dict(name='soilEC1', type='REAL'))
    assert title == 'Add column soilEC1'
    assert steps[0] is backups.create_step
    assert 'weewx-start' in cleanup[0]


def test_secrets_never_reach_the_page(station):
    config = settings.load()
    services.write_upload(config, 'Wunderground', dict(enable=True, station='IBER1', password='hunter2'))
    settings.save(config)
    described = services.read_uploads(settings.load())['Wunderground']
    assert 'hunter2' not in json.dumps(described)
    assert described['secrets_set'] == ['password'] and described['enable']
    config = settings.load()
    services.write_upload(config, 'Wunderground', dict(enable=True, station='IBER1', password=''))
    assert config['StdRESTful']['Wunderground']['password'] == 'hunter2'


def test_mapping_of_the_active_driver(station):
    config = settings.load()
    services.write_mapping(config, {'extraTemp1': 'tf_ch1'})
    assert config['Ecowittcustom']['sensor_map_extensions']['extraTemp1'] == 'tf_ch1'
    with pytest.raises(ValueError):
        services.write_mapping(config, {'bad name': 'x'})


def test_config_text_is_checked_before_it_replaces_the_file(station):
    with pytest.raises(ValueError):
        settings.write_text('[Station\n')
    with pytest.raises(ValueError):
        settings.write_text('[Other]\nkey = value\n')
    assert settings.read_text() == CONFIG


def test_newest_log_line_decides():
    log = ['Searching for transmitter(s) on channel 1', 'Receiving transmitter on channel 1']
    assert status.reception_message(log) == 'Receiving your station.'
    assert 'Searching' in status.reception_message(list(reversed(log)))


def test_jobs_run_one_at_a_time_and_cleanup_follows_failure():
    release = threading.Event()
    done = []
    first = jobs.start('first', [lambda job: release.wait(5)])
    with pytest.raises(jobs.Busy):
        jobs.start('second', [])
    release.set()
    while first.state == 'running':
        pass
    failing = jobs.start('failing', [lambda job: 1 / 0], [lambda job: done.append(True)])
    while failing.state == 'running':
        pass
    while not done:
        pass
    assert failing.state == 'failed' and done == [True]


@pytest.fixture
def api(station):
    instance = http.server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    threading.Thread(target=instance.serve_forever, daemon=True).start()

    def request(method, path, body=None, headers=None, cookie=None):
        connection = http.client.HTTPConnection('127.0.0.1', instance.server_port)
        send = {'X-Station-Admin': '1'} if headers is None else headers
        if cookie:
            send = dict(send, Cookie=cookie)
        connection.request(method, '/admin/api/' + path,
                           None if body is None else json.dumps(body), send)
        reply = connection.getresponse()
        return reply.status, reply.getheader('Set-Cookie'), json.loads(reply.read() or b'{}')

    yield request
    instance.shutdown()


def test_nothing_works_without_a_session(api):
    assert api('GET', 'status')[0] == 401
    assert api('GET', 'config')[0] == 401
    assert api('GET', 'backups/x.tar.gz/download')[0] == 401
    assert api('POST', 'system', dict(action='reboot'))[0] == 401


def test_first_password_opens_a_session_once(api):
    status_code, cookie, _ = api('POST', 'setup-password', dict(password='correct horse'))
    assert status_code == 200 and 'HttpOnly' in cookie and 'SameSite=Strict' in cookie
    assert api('POST', 'setup-password', dict(password='another password'))[0] == 403
    assert api('GET', 'backups', cookie=cookie.split(';')[0])[0] == 200


def test_posts_from_other_pages_are_refused(api):
    assert api('POST', 'setup-password', dict(password='correct horse'), headers={})[0] == 403
