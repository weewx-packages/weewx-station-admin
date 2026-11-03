# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""A WeeWX service that leaves the latest packet where the administration reads it."""

import json
import logging
import os
import time

import weeutil.config
import weewx
import weewx.defaults
import weewx.engine
import weewx.reportengine
import weewx.units

log = logging.getLogger(__name__)

LIVE_PATH = '/run/weewx/live.json'
SECONDS_BETWEEN_WRITES = 5


def report_units(config_dict):
    """Return the converter and formatter of the units on the weather pages.

    Args:
        config_dict (dict): The configuration of WeeWX.

    Returns:
        tuple[weewx.units.Converter, weewx.units.Formatter]: A two-way tuple
            (converter, formatter).
    """
    # The station page sets unit_system in [StdReport][[Defaults]], so the readings
    # follow the same steps WeeWX takes for a report, without the skin's own file.
    skin_dict = weeutil.config.deep_copy(weewx.defaults.defaults)
    defaults = weeutil.config.deep_copy(config_dict).get('StdReport', {}).get('Defaults', {})
    if 'unit_system' in defaults:
        weewx.reportengine.merge_unit_system(defaults['unit_system'], skin_dict)
    weeutil.config.merge_config(skin_dict, defaults)
    return (weewx.units.Converter.fromSkinDict(skin_dict),
            weewx.units.Formatter.fromSkinDict(skin_dict))


def readings(observations, converter, formatter):
    """Convert observations into the units of the weather pages, as text.

    Args:
        observations (dict): Values by name, in the units given by usUnits.
        converter (weewx.units.Converter): The units of the weather pages.
        formatter (weewx.units.Formatter): The formats and labels of those units.

    Returns:
        dict: The text of each reading by name (e.g., '5.4°C'). A value whose unit WeeWX
            does not know stays as the driver sent it, without a label.
    """
    result = {}
    for name, value in converter.convertDict(observations).items():
        unit, group = converter.getTargetUnit(name)
        if unit is None:
            result[name] = '%g' % value
        else:
            result[name] = formatter.toString(weewx.units.ValueTuple(value, unit, group))
    return result


class StationLive(weewx.engine.StdService):
    """Write each LOOP packet to memory-backed storage, a few seconds apart."""

    def __init__(self, engine, config_dict):
        super(StationLive, self).__init__(engine, config_dict)
        self.written = 0
        self.observations = {}
        # A change of units on the station page restarts WeeWX, which reads them anew.
        self.converter, self.formatter = report_units(config_dict)
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
                json.dump(dict(written=now, readings=readings(self.observations, self.converter,
                                                               self.formatter)), stream)
            os.replace(temporary, LIVE_PATH)
        except OSError as error:
            log.debug('Cannot write %s: %s', LIVE_PATH, error)
