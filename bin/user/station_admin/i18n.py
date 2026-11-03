# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""Languages of the administration.

The English text in the code is the key of each translation. The page and this server
read the same files in ui/i18n, so a text has one translation wherever it appears. A
text without a translation stays English.
"""

import json
import os
import threading

LANGUAGES = {'en': 'English', 'de': 'Deutsch'}
DEFAULT = 'en'
CATALOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui', 'i18n')

_catalogs = {}
# The page sends its language with every request, and a job keeps the language of the
# request that started it. Each request and each job has a thread of its own.
_current = threading.local()


def catalog(language):
    """Return the translations of a language.

    Args:
        language (str): A key of LANGUAGES.

    Returns:
        dict: The translation of each English text. Empty for English.
    """
    if language == DEFAULT or language not in LANGUAGES:
        return {}
    if language not in _catalogs:
        with open(os.path.join(CATALOG_DIR, language + '.json'), encoding='utf-8') as stream:
            _catalogs[language] = json.load(stream)
    return _catalogs[language]


def use(language):
    """Choose the language of the current thread.

    Args:
        language (str|None): A key of LANGUAGES. Anything else selects English.
    """
    _current.language = language if language in LANGUAGES else DEFAULT


def current():
    """Return the language of the current thread.

    Returns:
        str: A key of LANGUAGES.
    """
    return getattr(_current, 'language', DEFAULT)


def N_(text):
    """Mark a text for translation where it is defined, such as in a table.

    The place that shows the text translates it with _(). The mark lets the tests find
    every text that needs a translation.

    Args:
        text (str): The English text.

    Returns:
        str: The same text.
    """
    return text


def _(text, **values):
    """Translate a text into the language of the current thread.

    Args:
        text (str): The English text. Names in braces (e.g., '{name}') are filled from
            values.
        values (dict): The values of the names in the text.

    Returns:
        str: The translated text, with the values filled in.
    """
    translated = catalog(current()).get(text, text)
    return translated.format(**values) if values else translated
