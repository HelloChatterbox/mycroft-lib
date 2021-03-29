#
# Copyright 2018 Mycroft AI Inc.
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
"""Time utils for getting and converting datetime objects for the Mycroft
system. This time is based on the setting in the Mycroft config and may or
may not match the system locale.
"""
from dateutil.tz import gettz
from lingua_nostra.time import set_default_tz as _set_default_tz, now_utc, \
    now_local, to_local, to_utc, to_system, default_timezone as _default_tz


def set_default_tz(tz=None):
    if not tz:
        tz = default_timezone()
    _set_default_tz(tz)


def default_timezone():
    """Get the default timezone

    Based on user location settings location.timezone.code or
    the default system value if no setting exists.

    Returns:
        (datetime.tzinfo): Definition of the default timezone
    """
    try:
        # Obtain from user's configurated settings
        #   location.timezone.code (e.g. "America/Chicago")
        #   location.timezone.name (e.g. "Central Standard Time")
        #   location.timezone.offset (e.g. -21600000)
        from mycroft.configuration import Configuration
        config = Configuration.get()
        code = config["location"]["timezone"]["code"]

        return gettz(code)
    except Exception:
        # Just go with system default timezone
        return _default_tz()

