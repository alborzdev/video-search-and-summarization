"""Deny host lifecycle commands in CPU tests, even when a mock is missing."""

from pathlib import Path
import shlex
import subprocess
from unittest.mock import patch


def reject_host_mutation(command):
    args = shlex.split(command) if isinstance(command, str) else [str(arg) for arg in command]
    if not args:
        return
    program = Path(args[0]).name
    if program == 'systemctl':
        raise AssertionError('CPU tests must mock every systemctl call: ' + ' '.join(args))
    if program == 'docker':
        verbs = {'start', 'stop', 'restart', 'kill', 'rm', 'up', 'down', 'run', 'create', 'exec'}
        if any(arg in verbs for arg in args[1:]):
            raise AssertionError('CPU tests must mock Docker workload mutations: ' + ' '.join(args))


def install(test_case):
    actual_popen = subprocess.Popen

    def checked_popen(command, *args, **kwargs):
        reject_host_mutation(command)
        return actual_popen(command, *args, **kwargs)

    guard = patch.object(subprocess, 'Popen', side_effect=checked_popen)
    guard.start()
    test_case.addCleanup(guard.stop)
