# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Smoke tests of the administration, against a temporary station."""

import ast
import http.client
import http.server
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import tarfile
import threading
import time

import configobj
import pytest

from user.station_admin import (auth, backups, common, database, drivers, extensions, forms, i18n,
                                 jobs, links, live, server, services, settings, status)

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


def test_station_form_is_validated(station, monkeypatch):
    listing = 'C\nC.utf8\nPOSIX\nde_DE.utf8\nen_GB.utf8\nxx_YY.utf8\nxx_YY.iso88591\n'
    monkeypatch.setattr(settings.common, 'run',
                        lambda command, timeout: subprocess.CompletedProcess(command, 0, listing))
    assert settings.installed_languages() == {'de_DE.UTF-8': 'Deutsch (Deutschland)',
                                              'en_GB.UTF-8': 'English (United Kingdom)',
                                              'xx_YY.UTF-8': 'xx_YY'}
    good = dict(location='Garden', latitude='52,5', longitude='13.4', altitude='34',
                altitude_unit='meter', timezone='Europe/Berlin', units='metricwx',
                driver='ecowitt', port='8080', language='de_DE.UTF-8', title='Garden weather')
    settings_, errors = settings.parse_station(good)
    assert errors == [] and settings_['latitude'] == 52.5
    _, errors = settings.parse_station(dict(good, latitude='nan', driver='x', timezone='Mars'))
    assert len(errors) == 3
    _, errors = settings.parse_station(dict(good, language='fr_FR.UTF-8', title=' '))
    assert errors == ['The weather pages need a title.', 'Choose the language.']
    _, errors = settings.parse_station(dict(good, driver='rtldavis', band='EU', channel='12',
                                            bucket='1'))
    assert errors == ['Choose: ISS channel, as shown on the console.']
    _, errors = settings.parse_station(dict(good, port='80'))
    assert errors == ['Port must be between 1024 and 65535.']


def test_language_sets_both_options_of_belchertown(station):
    assert settings.read_station(settings.load())['language'] == settings.DEFAULT_LANGUAGE
    steps = settings.station_steps(dict(location='Garden', latitude=52.5, longitude=13.4,
                                        altitude=34.0, altitude_unit='meter', units='metricwx',
                                        timezone='Europe/Berlin', driver='ecowitt',
                                        options=dict(port='8081'), language='de_DE.UTF-8',
                                        title='Wetter, Garten'))
    for step in steps:
        if callable(step):
            step(Log())
    config = settings.load()
    assert config['StdReport']['Belchertown']['lang'] == 'de_DE.UTF-8'
    assert config['StdReport']['Belchertown']['Extras']['belchertown_locale'] == 'de_DE.UTF-8'
    assert settings.read_station(config)['language'] == 'de_DE.UTF-8'
    assert config['StdReport']['Belchertown']['Extras']['site_title'] == 'Wetter, Garten'
    assert settings.read_station(config)['title'] == 'Wetter, Garten'
    assert config['Ecowittcustom']['port'] == '8081'


def _steps_of(driver, monkeypatch, **options):
    monkeypatch.setattr(extensions, '_debian_packages', lambda package_id, repo: [['apt', package_id]])
    return settings.station_steps(dict(location='Garden', latitude=52.5, longitude=13.4,
                                       altitude=34.0, altitude_unit='meter', units='metricwx',
                                       timezone='Europe/Berlin', driver=driver, options=options,
                                       language='de_DE.UTF-8'))


def test_a_driver_comes_from_the_catalog_only_while_it_is_missing(station, monkeypatch):
    commands = [step for step in _steps_of('tempest', monkeypatch) if isinstance(step, list)]
    assert commands[0] == ['apt', 'tempest-udp']
    assert commands[1][:7] == ['python3', '-m', 'user.packages', 'install', 'tempest-udp',
                               '--repo', 'packages']
    assert '--pre' in commands[1]
    assert commands[2][:3] == ['weectl', 'station', 'reconfigure']
    assert '--driver=user.tempest_udp' in commands[2]
    (station / 'etc/bin/user/tempest_udp.py').write_text('# installed\n')
    commands = [step for step in _steps_of('tempest', monkeypatch) if isinstance(step, list)]
    assert commands[0][:3] == ['weectl', 'station', 'reconfigure']
    # A package below its own directory, as davis-cloud is.
    assert drivers.needs_package('davis-cloud') == ('davis-cloud', True)
    (station / 'etc/bin/user/daviscloud').mkdir()
    (station / 'etc/bin/user/daviscloud/driver.py').write_text('# installed\n')
    assert drivers.needs_package('davis-cloud') is None
    assert drivers.needs_package('rtldavis') is None


def test_only_the_fields_of_the_chosen_connection_count(station):
    config = settings.load()
    values, errors = drivers.parse('vantage', dict(connection='ethernet', device=''), config)
    assert errors == ['Enter: Address of the logger.']
    values, errors = drivers.parse('vantage', dict(connection='ethernet', host='192.0.2.5'), config)
    assert errors == [] and 'device' not in values
    drivers.apply('vantage', config, values)
    assert config['Vantage']['type'] == 'ethernet' and config['Vantage']['host'] == '192.0.2.5'


def test_secrets_stay_on_the_server_and_are_kept_when_left_empty(station):
    config = settings.load()
    form = dict(client_id='id', client_secret='client-secret', refresh_token='refresh-token')
    assert drivers.parse('netatmo', dict(form, refresh_token=''), config)[1] == [
        'Enter: Refresh token.']
    config['netatmo'] = dict(username='old', password='old', client_secret='INSERT_CLIENT_SECRET_HERE')
    values, errors = drivers.parse('netatmo', form, config)
    assert errors == []
    drivers.apply('netatmo', config, values)
    section = config['netatmo']
    assert section['client_secret'] == 'client-secret' and 'password' not in section
    with open(section['tokens_persistence_file']) as stream:
        assert json.load(stream) == dict(refresh_token='refresh-token')
    assert os.stat(section['tokens_persistence_file']).st_mode & 0o777 == 0o600

    page = json.dumps(drivers.describe(config))
    assert 'client-secret' not in page and 'refresh-token' not in page
    values, errors = drivers.parse('netatmo', dict(client_id='id'), config)
    assert errors == []
    drivers.apply('netatmo', config, values)
    assert config['netatmo']['client_secret'] == 'client-secret'
    with open(section['tokens_persistence_file']) as stream:
        assert json.load(stream) == dict(refresh_token='refresh-token')


def test_a_station_id_left_empty_removes_the_placeholder(station):
    config = settings.load()
    config['DavisCloud'] = dict(api_key='REPLACE_ME', api_secret='REPLACE_ME', station_id='REPLACE_ME')
    entry = [kind for kind in drivers.describe(config) if kind['key'] == 'davis-cloud'][0]
    assert [field['value'] for field in entry['fields']] == ['', '', '']
    values, errors = drivers.parse('davis-cloud', dict(api_key='k', api_secret='s'), config)
    assert errors == []
    drivers.apply('davis-cloud', config, values)
    assert 'station_id' not in config['DavisCloud']
    assert config['DavisCloud']['driver'] == 'user.daviscloud.driver'
    assert config['StdArchive']['record_generation'] == 'software'
    drivers.apply('wll', config, dict(host='192.0.2.5'))
    assert config['StdArchive']['record_generation'] == 'hardware'


def test_reception_ignores_what_an_earlier_driver_logged():
    lines = ['No RTL-SDR dongle found', 'INFO __main__: Initializing weewxd version 5.5.2',
             'ERROR could not open port']
    assert status.reception_message(lines) is None
    assert status.reception_message(lines + ['Waiting for broadcasts from a WeatherFlow hub'])


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


def test_a_session_outlasts_the_first_time_sync(station, monkeypatch):
    token = auth.open_session()
    # The date a Raspberry Pi boots with can be weeks behind the time server.
    wall_clock = time.time() + 28 * 86400
    monkeypatch.setattr(time, 'time', lambda: wall_clock)
    assert auth.session_valid(token)


def test_a_session_outlasts_a_restart_of_the_administration(station, monkeypatch):
    token = auth.open_session()
    stored = station / 'state' / 'sessions.json'
    assert token not in stored.read_text() and stored.stat().st_mode & 0o777 == 0o600
    # A new process of the service starts with nothing in memory.
    monkeypatch.setattr(auth, '_sessions', {})
    monkeypatch.setattr(auth, '_loaded', False)
    assert auth.session_valid(token)
    monkeypatch.setattr(auth, '_sessions', {})
    monkeypatch.setattr(auth, '_loaded', False)
    monkeypatch.setattr(auth, '_boot', lambda: 'the next boot')
    assert not auth.session_valid(token)


def test_a_new_password_ends_the_other_sessions(station):
    mine, other = auth.open_session(), auth.open_session()
    auth.set_password('another password', keep=mine)
    assert auth.session_valid(mine) and not auth.session_valid(other)


GITHUB = {
    'repos/a/released/releases/latest': dict(tag_name='v2', assets=[
        dict(name='notes.txt', browser_download_url='x'),
        dict(name='released-2.zip', browser_download_url='https://example.org/released-2.zip')]),
    'repos/a/early/releases?per_page=1': [dict(tag_name='v1a1', assets=[])],
    'repos/a/plain': dict(default_branch='master'),
}


def test_a_link_becomes_the_archive_it_stands_for(monkeypatch):
    monkeypatch.setattr(links, '_github', GITHUB.get)
    assert links.archive_url('https://github.com/a/released/')[0] == \
        'https://example.org/released-2.zip'
    assert links.archive_url('a/early')[0] == \
        'https://github.com/a/early/archive/refs/tags/v1a1.tar.gz'
    assert links.archive_url('https://github.com/a/plain.git?tab=readme')[0] == \
        'https://github.com/a/plain/archive/refs/heads/master.tar.gz'
    assert links.archive_url('https://github.com/a/plain/tree/dev')[0] == \
        'https://github.com/a/plain/archive/dev.tar.gz'
    assert links.archive_url('https://example.org/x.tar.gz')[0] == 'https://example.org/x.tar.gz'
    with pytest.raises(ValueError):
        links.archive_url('https://example.org/page.html')
    home = 'https://github.com/weewx-packages/weewx-wll'
    packages = [dict(id='wll', repo='packages', homepage=home)]
    assert links.catalog_package(home.replace('weewx-packages', 'Weewx-Packages'),
                                 packages)['id'] == 'wll'
    assert links.catalog_package('https://github.com/weewx-packages/weewx-wll/releases/tag/v1',
                                 packages) is None
    page = 'https://github.com/weewx-packages/catalog/blob/main/packages/wll.md'
    assert links.catalog_package(page, packages)['id'] == 'wll'


def test_the_catalogs_come_from_the_configuration(station):
    config = settings.load()
    config['ExtensionRepositories'] = {'packages': dict(url='https://a', enabled='True'),
                                       'more': dict(url='https://b', enabled='False')}
    assert [(item['alias'], item['enabled'], item['main'])
            for item in extensions.repositories(config)] == \
        [('packages', True, True), ('more', False, False)]
    assert extensions.repository_steps('add', 'more', 'https://b')[0][3:7] == \
        ['repo', 'add', 'more', 'https://b']
    with pytest.raises(ValueError):
        extensions.repository_steps('remove', 'packages')


SKIN = """
[Extras]
    # The title of every page
    site_title = "My Weather Website"
    station_observations = barometer, dewpoint
    mqtt_websockets_password = ""
"""


def test_a_skin_setting_overrides_skin_conf_from_weewx_conf(station):
    (station / 'etc/skins/Belchertown').mkdir()
    (station / 'etc/skins/Belchertown/skin.conf').write_text(SKIN)
    config = settings.load()
    config['StdReport']['Belchertown']['Extras'] = {'mqtt_websockets_password': 'secret'}
    extras = forms.describe(config, 'Belchertown')['sections'][0]['options']
    title, observations, password = extras
    assert (title['value'], title['default'], title['comment']) == \
        (None, 'My Weather Website', 'The title of every page')
    assert password['value'] == '' and password['stored']
    forms.apply(config, 'Belchertown', [
        dict(path=['Extras'], name='site_title', value='Garden, Berlin'),
        dict(path=['Extras'], name='station_observations', value='barometer, rain'),
        dict(path=['Extras'], name='mqtt_websockets_password', value='')])
    stored = config['StdReport']['Belchertown']['Extras']
    assert stored['site_title'] == 'Garden, Berlin'
    assert stored['station_observations'] == ['barometer', 'rain']
    assert stored['mqtt_websockets_password'] == 'secret'
    forms.apply(config, 'Belchertown', [dict(path=['Extras'], name='site_title', reset=True)])
    assert 'site_title' not in stored
    with pytest.raises(ValueError):
        forms.apply(config, '', [dict(path=['ExtensionRepositories'], name='url', value='x')])


def test_readings_follow_the_units_of_the_weather_pages():
    config = configobj.ConfigObj({'StdReport': {'Defaults': {'unit_system': 'metricwx'}}})
    converter, formatter = live.report_units(config)
    packet = dict(usUnits=1, outTemp=41.7, wh65_batt=0.0)
    assert live.readings(packet, converter, formatter) == dict(outTemp='5.4°C', wh65_batt='0')


def marked_texts():
    """Return every text the page and the server mark for translation."""
    package = pathlib.Path(i18n.__file__).parent
    script = (package / 'ui' / 'app.js').read_text(encoding='utf-8')
    texts = {match.replace("\\'", "'") for match in re.findall(r"\bt\('((?:[^'\\]|\\.)*)'", script)}
    # The tabs and the states of a job reach t() through a variable.
    texts.update(re.findall(r'^  async (\w+)\(\)', script, re.MULTILINE))
    texts.update(('running', 'done', 'failed'))
    for path in package.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Call) and getattr(node.func, 'id', None) in ('_', 'N_') \
                    and isinstance(node.args[0], ast.Constant):
                texts.add(node.args[0].value)
    return texts


def test_the_installer_ships_every_file_of_the_package():
    package = pathlib.Path(i18n.__file__).parent
    installer = (package.parents[2] / 'install.py').read_text()
    shipped = set(re.findall(r"'([\w.-]+\.(?:py|js|html|css|json))'", installer))
    present = {path.name for path in package.rglob('*')
               if path.is_file() and '__pycache__' not in path.parts}
    assert present <= shipped, present - shipped


def test_every_text_has_a_german_translation():
    german = i18n.catalog('de')
    placeholders = re.compile(r'\{\w+\}')
    for text in marked_texts():
        assert text in german, text
        assert set(placeholders.findall(text)) == set(placeholders.findall(german[text])), text


def test_the_server_answers_in_the_language_of_the_page(api):
    headers = {'X-Station-Admin': '1', 'X-Language': 'de'}
    reply = api('POST', 'setup-password', dict(password='short'), headers=headers)
    assert reply[2]['error'] == 'Das Passwort braucht mindestens 8 Zeichen.'
    assert api('POST', 'setup-password', dict(password='short'))[2]['error'].startswith('The')


def test_a_machine_without_a_raspberry_firmware_has_a_status(station):
    assert status.raspberry(False)['kernel'] == os.uname().release


def test_posts_from_other_pages_are_refused(api):
    assert api('POST', 'setup-password', dict(password='correct horse'), headers={})[0] == 403
