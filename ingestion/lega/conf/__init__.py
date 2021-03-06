"""Configuration Module provides a dictionary-like with configuration settings.

It also sets up the logging.

* The ``LEGA_LOG`` environment variable is used to configure where the logs go.
  Without it, there is no logging capabilities.
  Its content can be a path to an ``INI`` or ``YAML`` format, or a string
  representing the defaults loggers (ie default, debug, syslog, ...)

* The ``LEGA_CONF`` environment variable specifies the configuration settings.
  If not specified, this modules tries to load the default location ``/etc/ega/conf.ini``
  The files must be either in ``INI`` format or in ``YAML`` format, in
  which case, it must end in ``.yaml`` or ``.yml``.
"""
from . import logging as lega_logging
import logging
logging.setLoggerClass(lega_logging.LEGALogger)

import os
import configparser
import warnings
import stat
from logging.config import fileConfig, dictConfig
from pathlib import Path
import yaml
from yaml import SafeLoader as sf


LOG_FILE = os.getenv('LEGA_LOG', None)
CONF_FILE = os.getenv('LEGA_CONF', '/etc/ega/conf.ini')
LOG = logging.getLogger(__name__)

sf.add_constructor('tag:yaml.org,2002:python/tuple', lambda self, node: tuple(sf.construct_sequence(self, node)))


def get_from_file(filepath, mode='rb', remove_after=False):
    """Return file content.

    Raises ValueError if it errors.
    """
    try:
        with open(filepath, mode) as s:
            return s.read()
    except Exception as e:  # Crash if not found, or permission denied
        raise ValueError(f'Error loading {filepath}') from e
    finally:
        if remove_after:
            try:
                os.remove(filepath)
            except Exception:  # Crash if not found, or permission denied
                LOG.warning('Could not remove %s', filepath, exc_info=True)


def convert_sensitive(value):
    """Fetch a sensitive value from different sources.

    * If `value` starts with 'env://', we strip it out and the remainder acts as the name of an environment variable to read.
    If the environment variable does not exist, we raise a ValueError exception.

    * If `value` starts with 'file://', we strip it out and the remainder acts as the filepath of a file to read (in text mode).
    If any error occurs while read the file content, we raise a ValueError exception.

    * If `value` starts with 'secret://', we strip it out and the remainder acts as the filepath of a file to read (in binary mode), and we remove it after.
    If any error occurs while read the file content, we raise a ValueError exception.

    * If `value` starts with 'value://', we strip it out and the remainder acts as the value itself.
    It is used to enforce the value, in case its content starts with env:// or file:// (eg a file:// URL).

    * Otherwise, `value` is the value content itself.
    """
    if value is None:  # Not found
        return None

    # Short-circuit in case the value starts with value:// (ie, it is enforced)
    if value.startswith('value://'):
        return value[8:]

    if value.startswith('env://'):
        envvar = value[6:]
        LOG.debug('Loading value from env var: %s', envvar)
        warnings.warn(
            "Loading sensitive data from environment variable is not recommended "
            "and might be removed in future versions."
            " Use secret:// instead",
            DeprecationWarning, stacklevel=4
        )
        envvalue = os.getenv(envvar, None)
        if envvalue is None:
            raise ValueError(f'Environment variable {envvar} not found')
        return envvalue

    if value.startswith('file://'):
        path = value[7:]
        LOG.debug('Loading value from path: %s', path)
        statinfo = os.stat(path)
        if statinfo.st_mode & stat.S_IRGRP or statinfo.st_mode & stat.S_IROTH:
            warnings.warn(
                "Loading sensitive data from a file that is group or world readable "
                "is not recommended and might be removed in future versions."
                " Use secret:// instead",
                DeprecationWarning, stacklevel=4
            )
        return get_from_file(path, mode='rt')  # str

    if value.startswith('secret://'):
        path = value[9:]
        LOG.debug('Loading secret from path: %s', path)
        return get_from_file(path, mode='rb', remove_after=True)  # bytes

    # It's the value itself (even if it starts with postgres:// or amqp(s)://)
    return value


class Configuration(configparser.RawConfigParser):
    """Configuration from a config file."""

    logger = None

    def __init__(self):
        """Set up."""
        # Load the configuration settings
        configparser.RawConfigParser.__init__(self,
                                              delimiters=('=', ':'),
                                              comment_prefixes=('#', ';'),
                                              default_section='DEFAULT',
                                              interpolation=None,
                                              converters={
                                                  'sensitive': convert_sensitive,
                                              })
        if (
                not CONF_FILE  # has no value
                or
                not os.path.isfile(CONF_FILE)  # does not exist
                or
                not os.access(CONF_FILE, os.R_OK)  # is not readable
        ):
            warnings.warn("No configuration settings found", UserWarning, stacklevel=2)
        else:
            self.read([CONF_FILE], encoding='utf-8')

        # Configure the logging system
        if not LOG_FILE:
            warnings.warn("No logging supplied", UserWarning, stacklevel=2)
        else:
            try:
                self._load_log(LOG_FILE)
            except Exception as e:
                # import traceback
                # traceback.print_stack()
                warnings.warn(f"No logging supplied: {e!r}", UserWarning, stacklevel=3)
                if e.__cause__:
                    warnings.warn(f'Cause: {e.__cause__!r}', UserWarning, stacklevel=3)

    def __repr__(self):
        """Show the configuration files."""
        res = f'Configuration file: {CONF_FILE}'
        if self.logger:
            res += f'\nLogging settings loaded from {self.logger}'
        return res

    def _load_log(self, filename):
        """Try to load `filename` as configuration file for logging."""
        assert(filename)
        _here = Path(__file__).parent

        # Try first if it is a default logger
        _logger = _here / f'loggers/{filename}.yaml'
        if _logger.exists():
            with open(_logger, 'r') as stream:
                dictConfig(yaml.load(stream, Loader=sf))
                return _logger

        # Otherwise trying it as a path
        _filename = Path(filename)

        if not _filename.exists():
            raise ValueError(f"The file '{filename}' does not exist")

        if _filename.suffix in ('.yaml', '.yml'):
            with open(_filename, 'r') as stream:
                dictConfig(yaml.load(stream, Loader=sf))
                return filename

        if _filename.suffix in ('.ini', '.INI'):
            fileConfig(filename)
            return filename

        # Otherwise, fail
        raise ValueError(f"Unsupported log format for {filename}")


CONF = Configuration()
