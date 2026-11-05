"""Backward-compatible alias for :mod:`fitgirl_installer.translations`."""

import sys

from . import translations as _translations


# Keep legacy imports attached to the same module object so mutable language
# state and the localized builtins stay consistent during the transition.
sys.modules[__name__] = _translations
