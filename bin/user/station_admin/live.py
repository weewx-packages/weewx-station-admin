# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""A WeeWX service that leaves the latest packet where the administration reads it."""

import json
import logging
import os
import time

import weewx
import weewx.engine

log = logging.getLogger(__name__)

LIVE_PATH = '/run/weewx/live.json'
SECONDS_BETWEEN_WRITES = 5


class StationLive(weewx.engine.StdService):
    """Write each LOOP packet to memory-backed storage, a few seconds apart."""

    def __init__(self, engine, config_dict):
        super(StationLive, self).__init__(engine, config_dict)
        self.written = 0
        self.observations = {}
        self.bind(weewx.NEW_LOOP_PACKET, self.new_loop_packet)

    def new_loop_packet(self, event):
        # Davis and Ecowitt packets carry a few observations each, so the page
        # needs them collected to see every sensor.
        self.observations.update({name: value for name, value in event.packet.items()
                                  if isinstance(value, (int, float))})
        now = time.time()
        if now - self.written < SECONDS_BETWEEN_WRITES:
            return
        self.written = now
        temporary = LIVE_PATH + '.new'
        try:
            with open(temporary, 'w') as stream:
                json.dump(dict(written=now, observations=self.observations), stream)
            os.replace(temporary, LIVE_PATH)
        except OSError as error:
            log.debug('Cannot write %s: %s', LIVE_PATH, error)
