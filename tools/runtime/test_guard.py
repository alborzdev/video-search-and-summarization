import importlib.util
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
if __name__=='__main__':unittest.main()
