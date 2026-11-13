"""Recovery must not repeat a finished VIO or present a partial run as complete."""
from pathlib import Path
import tempfile
import unittest
import yaml
from run_poc_batch import resume_point,checkpoint


class ResumeTests(unittest.TestCase):
    def test_resume_uses_latest_completed_prerequisites(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.assertEqual(resume_point(root),(None,'all',False))
            for i,stages in enumerate((['prepare'],['prepare','reference'],
                                      ['prepare','reference','vio'],
                                      ['prepare','reference','vio','compare','report'])):
                run=root/str(i);run.mkdir()
                manifest={'started_utc':str(i),'stages':{s:{'status':'complete'} for s in stages}}
                (run/'manifest.yaml').write_text(yaml.safe_dump(manifest))
                expected=[(None,'all',False),(run,'all',False),(run,'compare',False),(run,None,True)][i]
                self.assertEqual(resume_point(root),expected)

    def test_running_vio_is_not_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'run';run.mkdir()
            (run/'manifest.yaml').write_text(yaml.safe_dump({'started_utc':'1','stages':{
                'prepare':{'status':'reused'},'reference':{'status':'complete'},'vio':{'status':'running'}}}))
            self.assertEqual(resume_point(root),(run,'all',False))
            checkpoint(root/'state.json',{'status':'running'})
            checkpoint(root/'state.json',{'status':'complete'})
            self.assertIn('complete',(root/'state.json').read_text())
            self.assertFalse((root/'state.json.tmp').exists())


if __name__=='__main__':unittest.main()
