# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""weewx.conf and the settings of each report, as forms.

The settings of a skin are not changed in its skin.conf. An update of the skin replaces
that file. WeeWX reads the section of the report in weewx.conf after skin.conf, so a
value set there overrides the skin and survives its updates. Belchertown asks for its
options to be set the same way.
"""

import os
import re
import shutil

import configobj

from user.station_admin import common, settings
from user.station_admin.i18n import _

# Options whose value must not reach the page. The page can only replace them.
SECRET = re.compile(r'pass(word|wd|code)|secret|token|api_?key', re.IGNORECASE)
# The package manager writes these and checks them. The Extensions page changes them.
HIDDEN = ('ExtensionRepositories',)
_RENDER = configobj.ConfigObj()


def text_of(value):
    """Return a value as weewx.conf writes it.

    Args:
        value (str|list[str]): The value.

    Returns:
        str: The text, with quotes and commas where ConfigObj needs them.
    """
    return _RENDER._quote(value) if isinstance(value, (list, tuple)) else str(value)


def value_of(text, listed):
    """Read a value from the form.

    Args:
        text (str): The text from the form.
        listed (bool): True if the option holds a list. Its text is read the way
            weewx.conf reads it, so commas separate the items. Any other text is kept
            as it is, commas included.

    Returns:
        str|list[str]: The value.

    Raises:
        ValueError: The text is no valid value.
    """
    if '\n' in text or '\r' in text:
        raise ValueError(_('A value has one line.'))
    if not listed:
        return text
    try:
        return configobj.ConfigObj(['value = ' + text], interpolation=False)['value']
    except (configobj.ConfigObjError, KeyError):
        raise ValueError(_('{text} is no valid value.', text=text))


def _comment(section, key):
    lines = list(section.comments.get(key, []))
    if section.inline_comments.get(key):
        lines.append(section.inline_comments[key])
    # Lines of only # and = frame headings in weewx.conf and say nothing.
    text = [line.strip().lstrip('#').strip() for line in lines]
    return '\n'.join(line for line in text if line and not re.fullmatch(r'[#=\-*\s]*', line))


def _option(section, key, defaults):
    """Describe one option for the page.

    Args:
        section (configobj.Section): The section that holds the value, or None.
        key (str): The name of the option.
        defaults (configobj.Section|None): The section of skin.conf with the default.

    Returns:
        dict: Name, value, default, comment, whether it is secret and whether a value
            is stored. Value is None where weewx.conf sets nothing, and default where
            skin.conf sets nothing. A secret's value and default are empty text.
    """
    secret = bool(SECRET.search(key))
    value = text_of(section[key]) if section is not None and key in section else None
    default = text_of(defaults[key]) if defaults is not None and key in defaults else None
    comment = _comment(defaults, key) if defaults is not None and key in defaults else ''
    if not comment and section is not None and key in section:
        comment = _comment(section, key)
    hide = (lambda text: None if text is None else '') if secret else (lambda text: text)
    return dict(name=key, value=hide(value), default=hide(default), comment=comment,
                secret=secret, stored=bool(value or default))


def _tree(section, defaults=None, name=None):
    """Describe a section and its subsections for the page.

    Args:
        section (configobj.Section|None): The values that weewx.conf holds.
        defaults (configobj.Section|None): The same section of skin.conf, for a report.
        name (str|None): The name of the section. None for the whole file.

    Returns:
        dict: The name, the comment, the options and the subsections.
    """
    sources = [part for part in (defaults, section) if part is not None]
    scalars, sections = [], []
    for part in sources:
        scalars.extend(key for key in part.scalars if key not in scalars)
        sections.extend(key for key in part.sections if key not in sections and key not in HIDDEN)
    parent = next((part.parent for part in sources if part is not part.parent), None)
    comment = _comment(parent, name) if name and parent is not None else ''
    return dict(name=name, comment=comment,
                options=[_option(section, key, defaults) for key in scalars],
                sections=[_tree(section.get(key) if section is not None else None,
                                defaults.get(key) if defaults is not None else None, key)
                          for key in sections])


def _skin_conf(config, report):
    """Read the skin.conf of a report.

    Args:
        config (configobj.ConfigObj): The configuration.
        report (str): The name of the report.

    Returns:
        configobj.ConfigObj: The skin's configuration.

    Raises:
        ValueError: There is no such report, or its skin has no skin.conf.
    """
    reports = config.get('StdReport', {})
    if report not in getattr(reports, 'sections', []):
        raise ValueError(_('Unknown report.'))
    path = os.path.join(common.SKIN_ROOT, reports[report].get('skin', ''), 'skin.conf')
    if not os.path.isfile(path):
        raise ValueError(_('The skin of {report} has no skin.conf.', report=report))
    return configobj.ConfigObj(path, encoding='utf-8', interpolation=False)


def forms(config):
    """Return what the settings page can edit.

    Args:
        config (configobj.ConfigObj): The configuration.

    Returns:
        list[dict]: The key and the skin of each report. weewx.conf itself has the key ''.
    """
    reports = config.get('StdReport', {})
    return [dict(key='', skin=None)] + [
        dict(key=name, skin=reports[name].get('skin', ''))
        for name in getattr(reports, 'sections', []) if 'skin' in reports[name]]


def describe(config, report=''):
    """Return the form of weewx.conf or of one report.

    Args:
        config (configobj.ConfigObj): The configuration.
        report (str): The name of a report. Empty for weewx.conf.

    Returns:
        dict: The tree of the form.

    Raises:
        ValueError: There is no such report, or its skin has no skin.conf.
    """
    if not report:
        return _tree(config)
    section = config['StdReport'][report]
    return _tree(section, _skin_conf(config, report))


def apply(config, report, changes):
    """Write the changes of a form into the configuration.

    Args:
        config (configobj.ConfigObj): The configuration, changed in place.
        report (str): The name of a report. Empty for weewx.conf.
        changes (list[dict]): Each with path, a list of section names below the form,
            name, and either value, the text from the form, or reset, true to drop the
            value from weewx.conf so that the skin's own applies again.

    Raises:
        ValueError: A change is not valid.
    """
    if report:
        defaults = _skin_conf(config, report)
        root = config['StdReport'][report]
    else:
        defaults, root = None, config
    for change in changes:
        path = [str(part) for part in change.get('path', [])]
        name = str(change.get('name', ''))
        if not name or (not report and path[:1] and path[0] in HIDDEN):
            raise ValueError(_('Unknown option.'))
        section = root
        for part in path:
            if change.get('reset'):
                section = section.get(part)
                if section is None:
                    break
            else:
                section = section.setdefault(part, {})
            if not isinstance(section, configobj.Section):
                raise ValueError(_('Unknown option.'))
        if change.get('reset'):
            if not report:
                raise ValueError(_('Unknown option.'))
            if section is not None:
                section.pop(name, None)
            continue
        if name in section.sections:
            raise ValueError(_('Unknown option.'))
        text = str(change.get('value', ''))
        # A secret arrives empty unless somebody typed a new one.
        if SECRET.search(name) and not text:
            continue
        default = defaults
        for part in path:
            default = default.get(part) if isinstance(default, configobj.Section) else None
        original = section.get(name, default.get(name) if isinstance(default, configobj.Section)
                               else None)
        section[name] = value_of(text, isinstance(original, list))


def save(config):
    """Replace weewx.conf, keeping one earlier copy, as the editor of the file does.

    Args:
        config (configobj.ConfigObj): The configuration.
    """
    shutil.copy2(common.CONFIG_PATH, common.CONFIG_PATH + '.previous')
    settings.save(config)
