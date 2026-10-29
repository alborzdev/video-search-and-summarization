# SPDX-License-Identifier: Apache-2.0
"""Locate the city runtime package without selecting another runtime implicitly.

VSS keeps its registrations, calibration archives, rules and tracker state in
its own repository. This path selects only the scene/publisher/control package.
Set VSS_ISAAC_CITY_ROOT before starting a VSS operator/controller process to
select another explicit absolute runtime root. Missing packages fail at use;
they never fall back to the retired city checkout.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Mapping

DEFAULT_RUNTIME_ROOT = Path('/home/sparkdev/Documents/ChatGPT/isaacsim-6/environments/city')
RUNTIME_ROOT_ENV = 'VSS_ISAAC_CITY_ROOT'
DEFAULT_WORKSPACE_SERVICE = 'isaac-workspace.service'
DEFAULT_RTSP_SERVICE = 'isaac-workspace-rtsp.service'
RETIRED_SERVICES = {'isaac-city-vss-demo.service', 'isaac-city-rtsp.service'}


def runtime_root(environ: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    if RUNTIME_ROOT_ENV not in values:
        return DEFAULT_RUNTIME_ROOT
    override = values[RUNTIME_ROOT_ENV]
    if not override.strip():
        raise ValueError(RUNTIME_ROOT_ENV + ' must be an explicit absolute runtime root')
    root = Path(override).expanduser()
    if not root.is_absolute():
        raise ValueError(RUNTIME_ROOT_ENV + ' must be an explicit absolute runtime root')
    return root.resolve()


def service_names(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    values = os.environ if environ is None else environ
    result = tuple(values.get(key, default) for key, default in (
        ('VSS_ISAAC_WORKSPACE_SERVICE', DEFAULT_WORKSPACE_SERVICE),
        ('VSS_ISAAC_RTSP_SERVICE', DEFAULT_RTSP_SERVICE)))
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}\.service', name)
           or name in RETIRED_SERVICES for name in result) or len(set(result)) != 2:
        raise ValueError('Select two distinct workspace service units; retired city units are unsupported')
    return result
