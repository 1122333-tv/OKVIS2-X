import tempfile
from pathlib import Path
import unittest
from compare_vio_graph_audits import compare_audits, read_audit

class GraphAudits(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
    def record(self,stamp,phase,value='aaa',unknown=0):
        return f'I log] REPRO_AUDIT timestamp_ns={stamp} phase={phase} iterations=2 parameters=10 residuals=20 unknown={unknown} values={value} measurements=bbb parameter_order=ccc residual_order=ddd\n'
    def file(self,name,text):
        p=self.root/name;p.write_text(text);return p
    def test_repeated_solves_keep_exact_frame_and_phase(self):
        text=''.join(self.record(t,phase) for t in (44613731516,44647068516,44647068516) for phase in ('before','after'))
        other=text.rsplit('values=aaa',1);other='values=abc'.join(other)
        r=compare_audits(self.file('a',text),self.file('b',other))
        self.assertTrue(r['structure_aligned'])
        d=r['first_differences']['values']
        self.assertEqual(d['timestamp_ns'],44647068516);self.assertEqual(d['solve_index'],2);self.assertEqual(d['phase'],'after')
        self.assertAlmostEqual(d['time_s'],0.033337)
    def test_reject_incomplete_or_unidentified_audits(self):
        for text in ('unrelated log',self.record(1,'before'),self.record(1,'before',unknown=1)+self.record(1,'after')):
            with self.assertRaises(ValueError):read_audit(self.file('a',text))
    def test_solver_schedule_difference_is_not_silently_aligned(self):
        a=self.record(1,'before')+self.record(1,'after')
        b=self.record(2,'before')+self.record(2,'after')
        r=compare_audits(self.file('a',a),self.file('b',b))
        self.assertFalse(r['structure_aligned']);self.assertFalse(r['fingerprints_equal'])

if __name__=='__main__':unittest.main()
