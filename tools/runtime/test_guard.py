import importlib.util
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('guard',Path(__file__).with_name('guard.py'))
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
class GuardTest(unittest.TestCase):
 def test_reserve_boundaries(self):
  self.assertEqual(guard.trip_reason(47.99,0,48),'reserve')
  self.assertIsNone(guard.trip_reason(48,0,48))
  self.assertEqual(guard.trip_reason(35.99,0,36),'reserve')
 def test_thermal_stall_with_plenty_of_memory(self):
  self.assertEqual(guard.trip_reason(100,10.01,48),'thermal_stall')
  self.assertIsNone(guard.trip_reason(100,10,48))
 def test_hung_docker_stop_is_bounded(self):
  with patch.object(guard.subprocess,'run',side_effect=subprocess.TimeoutExpired('docker',5)) as run:
   self.assertEqual(guard.halt('vss-memory-embed'),{'name':'vss-memory-embed','timeout':True})
   self.assertEqual(run.call_args.kwargs['timeout'],5)
 def test_fresh_checkout_guard_targets_only_its_compose_project(self):
  with patch.dict(os.environ,{'VSS_GUARD_PROJECT':'vss-thor'}),patch.object(guard.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'abc\ndef\n')) as run:
   self.assertEqual(guard.guard_targets(),['abc','def'])
   self.assertIn('label=com.docker.compose.project=vss-thor',run.call_args.args[0])
   self.assertEqual(run.call_args.kwargs['timeout'],5)
 def test_legacy_candidate_keeps_existing_target_list(self):
  with patch.dict(os.environ,{},clear=True):self.assertEqual(guard.guard_targets(),guard.TARGETS)
 def test_disk_full_still_stops_workloads(self):
  with patch.object(Path,'open',side_effect=OSError('disk full')),patch.object(guard,'guard_targets',return_value=['candidate']),patch.object(guard,'halt',return_value={'name':'candidate','code':0}) as halt:
   self.assertEqual(guard.trip({'available_gib':47},'reserve'),[{'name':'candidate','code':0}])
   halt.assert_called_once_with('candidate')
if __name__=='__main__':unittest.main()
