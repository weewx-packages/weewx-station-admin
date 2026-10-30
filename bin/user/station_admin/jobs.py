# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Long operations run one at a time in the background and log what they do."""

import itertools
import subprocess
import threading
import time
import os

from user.station_admin import common

_counter = itertools.count(1)
_jobs = {}
_lock = threading.Lock()


class Busy(Exception):
    """Another job is running."""


class Job:
    """One background operation.

    Attributes:
        id (int): Its number.
        title (str): What it does, for the page.
        state (str): 'running', 'done' or 'failed'.
        log (list[str]): Output so far.
    """

    def __init__(self, title):
        self.id = next(_counter)
        self.title = title
        self.state = 'running'
        self.log = []
        self.started = time.time()

    def write(self, line):
        """Add a line to the log.

        Args:
            line (str): The line.
        """
        self.log.append(line.rstrip())
        del self.log[:-2000]

    def describe(self, include_log=True):
        """Return the job for the page.

        Args:
            include_log (bool): True to include the log. Default is True.

        Returns:
            dict: Its fields.
        """
        fields = dict(id=self.id, title=self.title, state=self.state, started=self.started)
        if include_log:
            fields['log'] = '\n'.join(self.log)
        return fields


def _run_command(job, command):
    job.write('$ ' + ' '.join(command))
    environment = dict(os.environ, PYTHONPATH=common.PYTHON_PATH)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, errors='replace', env=environment)
    for line in process.stdout:
        job.write(line)
    process.wait()
    if process.returncode:
        raise RuntimeError('The command ended with code %d.' % process.returncode)


def _step(job, step):
    """Run one step, which is a command or a function taking the job."""
    if callable(step):
        step(job)
    else:
        _run_command(job, step)


def _work(job, steps, cleanup):
    try:
        for step in steps:
            _step(job, step)
        job.state = 'done'
    except Exception as error:
        job.write('Failed: %s' % error)
        job.state = 'failed'
    # Cleanup runs after a failure too: a failed change of the database must not
    # leave the station stopped.
    for step in cleanup:
        try:
            _step(job, step)
        except Exception as error:
            job.write('Failed: %s' % error)
            job.state = 'failed'


def start(title, steps, cleanup=()):
    """Start a job.

    Args:
        title (str): What it does.
        steps (Iterable[list[str]|Callable[[Job], None]]): Commands, or functions
            called as step(job). The first failure ends the sequence.
        cleanup (Iterable[list[str]|Callable[[Job], None]]): Steps that always run
            at the end.

    Returns:
        Job: The started job.

    Raises:
        Busy: Another job is running.
    """
    with _lock:
        if any(job.state == 'running' for job in _jobs.values()):
            raise Busy('Another operation is still running.')
        job = Job(title)
        _jobs[job.id] = job
        for old in sorted(_jobs)[:-20]:
            del _jobs[old]
    threading.Thread(target=_work, args=(job, list(steps), list(cleanup)), daemon=True).start()
    return job


def get(number):
    """Return a job by number.

    Args:
        number (int): Its id.

    Returns:
        Job|None: The job, or None if it is unknown.
    """
    return _jobs.get(number)


def recent():
    """Return the recent jobs, newest first.

    Returns:
        list[dict]: Their fields, without logs.
    """
    return [job.describe(False) for job in sorted(_jobs.values(), key=lambda job: -job.id)]
