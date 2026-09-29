import pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[2]
class TrackerBackendTest(unittest.TestCase):
 def test_existing_pva_configuration_is_replaced_idempotently(self):
  source=(ROOT/'deploy/docker/services/rtvi/rtvi-cv/ds-start.sh').read_text()
  functions=source[source.index('is_thor_profile()'):source.index('apply_tracker_reid_mode()')]
  with tempfile.TemporaryDirectory() as tmp:
   c=pathlib.Path(tmp)/'app.ini';t=pathlib.Path(tmp)/'tracker.yml'
   c.write_text('[source-list]\nmax-batch-size=4\n[tracker]\ncompute-hw=2\n[tests]\n')
   t.write_text('TargetManagement:\n  maxTargetsPerStream: 150\nVisualTracker:\n  visualTrackerType: 2\n  vpiBackend4DcfTracker: 2\nReID:\n  reidType: 0\n')
   script=functions+'\nHARDWARE_PROFILE=AGX-THOR\napply_thor_tracker_tuning "$1" "$2"\napply_thor_tracker_tuning "$1" "$2"\n'
   subprocess.run(['bash','-eu','-c',script,'test',str(c),str(t)],check=True,capture_output=True)
   self.assertEqual(t.read_text().count('vpiBackend4DcfTracker: 1'),1)
   self.assertNotIn('vpiBackend4DcfTracker: 2',t.read_text())
   self.assertIn('maxTargetsPerStream: 50',t.read_text())
if __name__=='__main__':unittest.main()
