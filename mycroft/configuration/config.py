# Copyright 2017 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import json
import re
from os.path import isfile

import inflection
from requests import RequestException

from mycroft.configuration.locations import *
from mycroft.util.json_helper import load_commented_json, merge_dict
from mycroft.util.log import LOG


def is_remote_list(values):
    """Check if list corresponds to a backend formatted collection of dicts
    """
    for v in values:
        if not isinstance(v, dict):
            return False
        if "@type" not in v.keys():
            return False
    return True


def translate_remote(config, setting):
    """Translate config names from server to equivalents for mycroft-core.

    Args:
        config:     base config to populate
        settings:   remote settings to be translated
    """
    IGNORED_SETTINGS = ["uuid", "@type", "active", "user", "device"]

    for k, v in setting.items():
        if k not in IGNORED_SETTINGS:
            # Translate the CamelCase values stored remotely into the
            # Python-style names used within mycroft-core.
            key = inflection.underscore(re.sub(r"Setting(s)?", "", k))
            if isinstance(v, dict):
                config[key] = config.get(key, {})
                translate_remote(config[key], v)
            elif isinstance(v, list):
                if is_remote_list(v):
                    if key not in config:
                        config[key] = {}
                    translate_list(config[key], v)
                else:
                    config[key] = v
            else:
                config[key] = v


def translate_list(config, values):
    """Translate list formated by mycroft server.

    Args:
        config (dict): target config
        values (list): list from mycroft server config
    """
    for v in values:
        module = v["@type"]
        if v.get("active"):
            config["module"] = module
        config[module] = config.get(module, {})
        translate_remote(config[module], v)


class LocalConf(dict):
    """Config dictionary from file."""

    def __init__(self, path):
        super(LocalConf, self).__init__()
        self.is_valid = True  # is loaded json valid, updated when load occurs
        if path:
            self.path = path
            self.load_local(path)

    def load_local(self, path):
        """Load local json file into self.

        Args:
            path (str): file to load
        """
        if exists(path) and isfile(path):
            try:
                config = load_commented_json(path)
                for key in config:
                    self.__setitem__(key, config[key])

                LOG.debug("Configuration {} loaded".format(path))
            except Exception as e:
                LOG.error("Error loading configuration '{}'".format(path))
                LOG.error(repr(e))
                self.is_valid = False
        else:
            LOG.debug("Configuration '{}' not defined, skipping".format(path))

    def store(self, path=None, force=False):
        """Save config to disk.

        The cache will be used if the remote is unreachable to load settings
        that are as close to the user's as possible.

        path (str): path to store file to, if missing will use the path from
                    where the config was loaded.
        force (bool): Set to True if writing should occur despite the original
                      was malformed.

        Returns:
            (bool) True if save was successful, else False.
        """
        result = False
        path = path or self.path
        if self.is_valid or force:
            # Only write settings
            with open(path, 'w') as f:
                json.dump(self, f, indent=2)
            result = True
        else:
            LOG.warning(('"{}" was not a valid config file when loaded, '
                         'will not save config. Please correct the json or '
                         'remove it to allow updates.').format(path))
            result = False
        return result

    def merge(self, conf):
        merge_dict(self, conf)


class RemoteConf(LocalConf):
    """Config dictionary fetched from mycroft.ai."""

    def __init__(self, cache=None):
        super(RemoteConf, self).__init__(None)
        cache = cache or get_webcache_location()

        try:
            # Here to avoid cyclic import
            from mycroft.api import is_paired
            from mycroft.api import DeviceApi
            from mycroft.api import is_backend_disabled

            if not is_paired():
                self.load_local(cache)
                return

            if is_backend_disabled():
                # disable options that require backend
                config = {
                    "server": {
                        "metrics": False,
                        "sync_skill_settings": False
                    },
                    "skills": {"upload_skill_manifest": False},
                    "opt_in": False
                }
                for key in config:
                    self.__setitem__(key, config[key])
            else:
                api = DeviceApi()
                setting = api.get_settings()
                location = None
                try:
                    location = api.get_location()
                except RequestException as e:
                    LOG.error("RequestException fetching remote location: {}"
                              .format(str(e)))
                    if exists(cache) and isfile(cache):
                        location = load_commented_json(cache).get('location')

                if location:
                    setting["location"] = location
                # Remove server specific entries
                config = {}
                translate_remote(config, setting)

                for key in config:
                    self.__setitem__(key, config[key])
                self.store(cache, force=True)

        except RequestException as e:
            LOG.error("RequestException fetching remote configuration: {}"
                      .format(str(e)))
            self.load_local(cache)

        except Exception as e:
            LOG.error("Failed to fetch remote configuration: %s" % repr(e),
                      exc_info=True)
            self.load_local(cache)


def _warn_xdg_config(old_user_config):
    LOG.warning(" ===============================================")
    LOG.warning(" ==             DEPRECATION WARNING           ==")
    LOG.warning(" ===============================================")
    LOG.warning(f" You still have a config file at {old_user_config}")
    LOG.warning(" Note that this location is deprecated and will" +
                " not be used in the future")
    LOG.warning(" Please move it to " + join(XDG.xdg_config_home,
                                             get_xdg_base()))


def is_using_xdg_config():
    default_config, system_config, old_user_config = \
        get_config_locations(default=True,
                             web_cache=False,
                             system=True,
                             old_user=True,
                             user=False)
    # HolmesV feature: optional XDG
    # load all non XDG configs, and check if XDG is disabled
    # TODO deprecate this once mycroft-core moves to XDG
    # (or just change default .conf value)
    _config = Configuration.load_config_stack(
        [default_config, system_config, old_user_config],
        cache=False, remote=False)
    return not _config.get("disable_xdg")


class Configuration:
    """Namespace for operations on the configuration singleton."""
    __config = {}  # Cached config
    __patch = {}  # Patch config that skills can update to override config

    @staticmethod
    def get(configs=None, cache=True, remote=True):
        """Get configuration

        Returns cached instance if available otherwise builds a new
        configuration dict.

        Args:
            configs (list): List of configuration dicts
            cache (boolean): True if the result should be cached
            remote (boolean): False if the Mycroft Home settings shouldn't
                              be loaded


        Returns:
            (dict) configuration dictionary.
        """
        if Configuration.__config:
            return Configuration.__config
        else:
            return Configuration.load_config_stack(configs, cache, remote)

    @staticmethod
    def load_config_stack(configs=None, cache=False, remote=True):
        """Load a stack of config dicts into a single dict

        Args:
            configs (list): list of dicts to load
            cache (boolean): True if result should be cached
            remote (boolean): False if the Mycroft Home settings shouldn't
                              be loaded
        Returns:
            (dict) merged dict of all configuration files
        """
        if not configs:
            default_config, system_config, old_user_config = \
                get_config_locations(default=True,
                                     system=True,
                                     web_cache=False,
                                     old_user=True,
                                     user=False)

            configs = [LocalConf(default_config), LocalConf(system_config),
                       RemoteConf()] if remote \
                else [LocalConf(default_config), LocalConf(system_config)]

            if is_using_xdg_config():
                # deprecation warning
                if isfile(old_user_config):
                    _warn_xdg_config(old_user_config)
                    configs.append(LocalConf(old_user_config))

                # This includes both the user config and
                # /etc/xdg/mycroft/mycroft.conf
                configs += [LocalConf(p) for p in get_xdg_config_locations()]

                configs.append(Configuration.__patch)
            else:
                # just load the pre defined locations
                configs += [LocalConf(old_user_config),
                            Configuration.__patch]

        else:
            # Handle strings in stack
            for index, item in enumerate(configs):
                if isinstance(item, str):
                    configs[index] = LocalConf(item)

        # Merge all configs into one
        base = {}
        for c in configs:
            merge_dict(base, c)

        # copy into cache
        if cache:
            Configuration.__config.clear()
            for key in base:
                Configuration.__config[key] = base[key]
            return Configuration.__config
        else:
            return base

    @staticmethod
    def set_config_update_handlers(bus):
        """Setup websocket handlers to update config.

        Args:
            bus: Message bus client instance
        """
        bus.on("configuration.updated", Configuration.updated)
        bus.on("configuration.patch", Configuration.patch)
        bus.on("configuration.patch.clear", Configuration.patch_clear)

    @staticmethod
    def updated(message):
        """Handler for configuration.updated,

        Triggers an update of cached config.
        """
        Configuration.load_config_stack(cache=True)

    @staticmethod
    def patch(message):
        """Patch the volatile dict usable by skills

        Args:
            message: Messagebus message should contain a config
                     in the data payload.
        """
        config = message.data.get("config", {})
        merge_dict(Configuration.__patch, config)
        Configuration.load_config_stack(cache=True)

    @staticmethod
    def patch_clear(message):
        """Clear the config patch space.

        Args:
            message: Messagebus message should contain a config
                     in the data payload.
        """
        Configuration.__patch = {}
        Configuration.load_config_stack(cache=True)
