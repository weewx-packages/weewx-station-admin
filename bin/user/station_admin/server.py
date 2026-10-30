# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""HTTP server of the administration.

The server listens on the loopback interface only. nginx in front of it serves
the weather pages and refuses addresses outside the local network.
"""

import http.cookies
import http.server
import json
import os
import shutil
import time
import urllib.parse
import uuid

from user.station_admin import (VERSION, auth, backups, common, database, extensions, jobs,
                                services, settings, status)

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui')
STATIC = {'/admin/': ('index.html', 'text/html; charset=utf-8'),
          '/admin/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/admin/style.css': ('style.css', 'text/css; charset=utf-8')}
COOKIE = 'station_admin'
MAX_JSON = 4 * 1024 * 1024
MAX_UPLOAD = 2 * 1024 * 1024 * 1024
# The browser adds this header only for scripts of this page, and a page from
# elsewhere cannot set it without a CORS approval, which this server never gives.
CSRF_HEADER = 'X-Station-Admin'


class Reply(Exception):
    """Ends a request with an error message for the page.

    Attributes:
        code (int): HTTP status.
        message (str): Text for the user.
    """

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _job_reply(job):
    return dict(job=job.id)


def _start(title, steps, cleanup=()):
    try:
        return _job_reply(jobs.start(title, steps, cleanup))
    except jobs.Busy as error:
        raise Reply(409, str(error))


def _configured():
    return common.run(['systemctl', 'is-enabled', 'weewx'], 10).stdout.strip() == 'enabled'


def get_session(handler):
    return dict(password_set=auth.has_password(), authenticated=handler.authenticated(),
                version=VERSION)


def post_setup_password(handler, body):
    # Only the first visitor gets this far: afterwards a password exists.
    if auth.has_password():
        raise Reply(403, 'The password is already set.')
    try:
        auth.set_password(str(body.get('password', '')))
    except ValueError as error:
        raise Reply(400, str(error))
    handler.open_session()
    return {}


def post_login(handler, body):
    if not auth.check_password(str(body.get('password', ''))):
        time.sleep(1)
        raise Reply(403, 'Wrong password, or too many attempts. Wait a minute.')
    handler.open_session()
    return {}


def post_logout(handler, body):
    auth.close_session(handler.session_token())
    return {}


def post_password(handler, body):
    if not auth.check_password(str(body.get('current', ''))):
        raise Reply(403, 'The current password is wrong.')
    try:
        auth.set_password(str(body.get('new', '')))
    except ValueError as error:
        raise Reply(400, str(error))
    return {}


def get_status(handler):
    return status.read()


def get_station(handler):
    config = settings.load()
    return dict(values=settings.read_station(config), address=status.host_address(),
                configured=_configured(),
                timezone=common.run(['timedatectl', 'show', '-p', 'Timezone', '--value'],
                                    10).stdout.strip())


def post_station(handler, body):
    parsed, errors = settings.parse_station(body)
    if errors:
        raise Reply(400, ' '.join(errors))
    return _start('Save the station settings', settings.station_steps(parsed))


def get_sensors(handler):
    names = [column['name'] for column in database.columns()['columns']]
    return services.read_sensors(settings.load(), names)


def post_sensors(handler, body):
    config = settings.load()
    try:
        services.write_mapping(config, body.get('mapping', {}))
    except ValueError as error:
        raise Reply(400, str(error))
    settings.save(config)
    return _start('Apply the sensor map', [common.privileged('weewx-restart')])


def get_database(handler):
    return database.columns()


def post_database(handler, body):
    try:
        title, steps, cleanup = database.change_steps(body.get('action'), body)
    except ValueError as error:
        raise Reply(400, str(error))
    return _start(title, steps, cleanup)


def get_extensions(handler):
    try:
        catalog, error = extensions.catalog(), None
    except OSError as problem:
        catalog, error = [], 'The catalog cannot be read: %s' % problem
    return dict(installed=extensions.installed(), catalog=catalog, error=error)


def post_extensions(handler, body):
    action = body.get('action')
    name = str(body.get('name', ''))
    try:
        if action == 'install':
            return _start('Install %s' % name, extensions.install_steps(name))
        if action == 'update':
            return _start('Update %s' % name, extensions.update_steps(name))
        if action == 'update-all':
            return _start('Update all packages', extensions.update_steps())
        if action == 'remove':
            return _start('Remove %s' % name, extensions.remove_steps(name))
    except ValueError as error:
        raise Reply(400, str(error))
    raise Reply(400, 'Unknown action.')


def put_extension_upload(handler, query):
    path = handler.store_upload()
    return _start('Install an uploaded extension', extensions.upload_steps(path),
                  [lambda job: os.remove(path)])


def get_reports(handler):
    return dict(reports=services.read_reports(settings.load()))


def post_reports(handler, body):
    if body.get('action') == 'generate':
        return _start('Generate the reports',
                      [['weectl', 'report', 'run', '--config=' + common.CONFIG_PATH]])
    config = settings.load()
    try:
        services.write_report(config, str(body.get('name')), bool(body.get('enable')))
    except ValueError as error:
        raise Reply(400, str(error))
    settings.save(config)
    return _start('Apply the report settings', [common.privileged('weewx-restart')])


def get_uploads(handler):
    return dict(services=services.read_uploads(settings.load()))


def post_uploads(handler, body):
    config = settings.load()
    try:
        services.write_upload(config, str(body.get('name')), body.get('values', {}))
    except ValueError as error:
        raise Reply(400, str(error))
    settings.save(config)
    return _start('Apply the upload settings', [common.privileged('weewx-restart')])


def get_backups(handler):
    return dict(backups=backups.listing())


def post_backups(handler, body):
    action = body.get('action')
    try:
        if action == 'create':
            return _start('Create a backup', [backups.create_step])
        if action == 'delete':
            backups.remove(str(body.get('name')))
            return {}
        if action == 'restore':
            return _start('Restore %s' % body.get('name'),
                          [common.privileged('weewx-stop'),
                           backups.restore_step(str(body.get('name')))],
                          [common.privileged('weewx-start')])
    except ValueError as error:
        raise Reply(400, str(error))
    raise Reply(400, 'Unknown action.')


def put_backup_upload(handler, query):
    name = time.strftime('uploaded-%Y%m%d-%H%M%S.tar.gz')
    os.makedirs(common.BACKUP_DIR, mode=0o700, exist_ok=True)
    os.replace(handler.store_upload(), os.path.join(common.BACKUP_DIR, name))
    return dict(name=name)


def get_config(handler):
    return dict(text=settings.read_text())


def post_config(handler, body):
    try:
        settings.write_text(str(body.get('text', '')))
    except ValueError as error:
        raise Reply(400, str(error))
    return _start('Apply the configuration', [common.privileged('weewx-restart')])


def post_system(handler, body):
    action = body.get('action')
    if action == 'restart-weewx':
        return _start('Restart WeeWX', [common.privileged('weewx-restart')])
    if action == 'upgrade':
        return _start('Update the system', [common.privileged('apt-upgrade')])
    if action in ('reboot', 'poweroff'):
        return _start(action.capitalize(), [common.privileged(action)])
    raise Reply(400, 'Unknown action.')


def get_jobs(handler):
    return dict(jobs=jobs.recent())


GET = {'session': (get_session, False), 'status': (get_status, True),
       'station': (get_station, True), 'sensors': (get_sensors, True),
       'database': (get_database, True), 'extensions': (get_extensions, True),
       'reports': (get_reports, True), 'uploads': (get_uploads, True),
       'backups': (get_backups, True), 'config': (get_config, True),
       'jobs': (get_jobs, True)}
POST = {'setup-password': (post_setup_password, False), 'login': (post_login, False),
        'logout': (post_logout, True), 'password': (post_password, True),
        'station': (post_station, True), 'sensors': (post_sensors, True),
        'database': (post_database, True), 'extensions': (post_extensions, True),
        'reports': (post_reports, True), 'uploads': (post_uploads, True),
        'backups': (post_backups, True), 'config': (post_config, True),
        'system': (post_system, True)}
PUT = {'extensions/upload': put_extension_upload, 'backups/upload': put_backup_upload}


class Handler(http.server.BaseHTTPRequestHandler):
    """Serve the page and its JSON interface."""

    protocol_version = 'HTTP/1.1'
    new_session = None

    def log_message(self, format, *args):
        """Keep the polling of the page out of the journal."""

    def session_token(self):
        cookies = http.cookies.SimpleCookie(self.headers.get('Cookie', ''))
        return cookies[COOKIE].value if COOKIE in cookies else None

    def authenticated(self):
        return auth.session_valid(self.session_token())

    def open_session(self):
        self.new_session = auth.open_session()

    def reply(self, code, content_type, data, extra=()):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        if self.new_session:
            self.send_header('Set-Cookie', '%s=%s; Path=/admin/; HttpOnly; SameSite=Strict'
                             % (COOKIE, self.new_session))
            self.new_session = None
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def reply_json(self, value, code=200):
        self.reply(code, 'application/json', json.dumps(value).encode('utf-8'))

    def handle_api(self, work):
        """Run the work of a request and turn its outcome into a reply.

        Args:
            work (Callable[[], dict]): Called as work(). Returns the reply.
        """
        try:
            self.reply_json(work())
        except Reply as reply:
            self.reply_json(dict(error=reply.message), reply.code)
        except OSError as error:
            self.reply_json(dict(error=str(error)), 500)

    def require(self, needs_login):
        if needs_login and not self.authenticated():
            raise Reply(401, 'Log in first.')

    def require_page(self):
        if not self.headers.get(CSRF_HEADER):
            raise Reply(403, 'This request did not come from the page.')

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in STATIC:
            name, content_type = STATIC[path]
            with open(os.path.join(UI_DIR, name), 'rb') as stream:
                self.reply(200, content_type, stream.read())
            return
        if path.startswith('/admin/api/backups/') and path.endswith('/download'):
            self.download(path.split('/')[4])
            return
        if path.startswith('/admin/api/jobs/'):
            self.handle_api(lambda: self.job(path.rsplit('/', 1)[1]))
            return
        name = path[len('/admin/api/'):] if path.startswith('/admin/api/') else None
        if name not in GET:
            self.reply_json(dict(error='Not found.'), 404)
            return
        function, needs_login = GET[name]

        def work():
            self.require(needs_login)
            return function(self)

        self.handle_api(work)

    def job(self, number):
        self.require(True)
        job = jobs.get(int(number)) if number.isdigit() else None
        if job is None:
            raise Reply(404, 'No such job.')
        return job.describe()

    def download(self, name):
        if not self.authenticated():
            self.reply_json(dict(error='Log in first.'), 401)
            return
        try:
            path = backups.path_of(name)
        except ValueError as error:
            self.reply_json(dict(error=str(error)), 404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/gzip')
        self.send_header('Content-Length', str(os.path.getsize(path)))
        self.send_header('Content-Disposition', 'attachment; filename="%s"' % name)
        self.end_headers()
        with open(path, 'rb') as stream:
            shutil.copyfileobj(stream, self.wfile, 1024 * 1024)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        name = path[len('/admin/api/'):] if path.startswith('/admin/api/') else None
        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_JSON:
            self.close_connection = True
            self.reply_json(dict(error='The request is too large.'), 413)
            return
        raw = self.rfile.read(length)

        def work():
            self.require_page()
            if name not in POST:
                raise Reply(404, 'Not found.')
            function, needs_login = POST[name]
            self.require(needs_login)
            try:
                body = json.loads(raw or b'{}')
            except ValueError:
                raise Reply(400, 'The request is no JSON.')
            return function(self, body)

        self.handle_api(work)

    def do_PUT(self):
        path = urllib.parse.urlsplit(self.path).path
        name = path[len('/admin/api/'):] if path.startswith('/admin/api/') else None

        def work():
            self.require_page()
            self.require(True)
            if name not in PUT:
                raise Reply(404, 'Not found.')
            return PUT[name](self, urllib.parse.urlsplit(self.path).query)

        self.handle_api(work)

    def store_upload(self):
        """Write the request body to a new file.

        Returns:
            str: Its path. The name keeps the suffix weectl needs to read it.

        Raises:
            Reply: The upload is too large for this station.
        """
        length = int(self.headers.get('Content-Length') or 0)
        if not 0 < length < MAX_UPLOAD:
            self.close_connection = True
            raise Reply(413, 'The upload is empty or too large.')
        if shutil.disk_usage(common.STATE_DIR).free < 2 * length:
            self.close_connection = True
            raise Reply(507, 'Not enough free space.')
        name = os.path.basename(urllib.parse.parse_qs(
            urllib.parse.urlsplit(self.path).query).get('name', ['upload.tar.gz'])[0])
        suffix = '.zip' if name.endswith('.zip') else '.tar.gz'
        os.makedirs(common.UPLOAD_DIR, mode=0o700, exist_ok=True)
        path = os.path.join(common.UPLOAD_DIR, uuid.uuid4().hex + suffix)
        remaining = length
        with open(path, 'wb') as stream:
            while remaining:
                block = self.rfile.read(min(remaining, 1024 * 1024))
                if not block:
                    break
                stream.write(block)
                remaining -= len(block)
        return path


def serve(port=common.PORT):
    """Run the server until the service stops.

    Args:
        port (int): TCP port on the loopback interface.
    """
    os.makedirs(common.STATE_DIR, mode=0o700, exist_ok=True)
    http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
