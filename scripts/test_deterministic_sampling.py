"""CLI, provenance and compatibility contracts for sampling-only determinism."""
import argparse
import subprocess
import tempfile
from pathlib import Path
import unittest
from vio_pipeline_common import add_sampling_argument, sampling_settings, sampling_arguments

ROOT = Path(__file__).resolve().parents[1]

class SamplingOptions(unittest.TestCase):
    def parse(self, *args):
        parser = argparse.ArgumentParser()
        add_sampling_argument(parser)
        return parser.parse_args(args).deterministic

    def test_cli(self):
        self.assertIsNone(self.parse())
        self.assertEqual(self.parse('--deterministic'), 1)
        self.assertEqual(self.parse('--deterministic', '1'), 1)
        self.assertEqual(self.parse('--deterministic', '0'), 0)
        for value in ('2', '-1', 'true', 'abc'):
            with self.assertRaises(SystemExit): self.parse('--deterministic', value)

    def test_inheritance_and_override(self):
        self.assertFalse(sampling_settings(None)['deterministic'])
        self.assertFalse(sampling_settings(None, {'vio': {}})['deterministic'])
        prior = {'sampling': sampling_settings(1)}
        self.assertEqual(sampling_settings(None, prior), prior['sampling'])
        self.assertFalse(sampling_settings(0, prior)['deterministic'])
        self.assertIsNone(sampling_settings(0, prior)['seed'])
        self.assertEqual(sampling_settings(1)['seed'], 12345)

    def test_forwarding(self):
        self.assertEqual(sampling_arguments(sampling_settings(1)), ['--deterministic','1'])
        self.assertEqual(sampling_arguments(sampling_settings(0)), [])

    def test_cannot_relabel_saved_trajectory(self):
        import sys
        for step in ('compare', 'report'):
            result = subprocess.run([sys.executable, str(ROOT/'scripts/run_vio_pipeline.py'),
                                     '--step',step,'--deterministic','1'],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('cannot relabel',result.stderr)

    def test_report_records_actual_mode(self):
        import json
        import yaml
        from generate_pipeline_report import generate
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            m = dict(format='okvis-vio',version=2,status='complete',parameters={},stages={},
                     sampling=sampling_settings(1))
            (run/'manifest.yaml').write_text(yaml.safe_dump(m))
            page = generate(run).read_text()
            self.assertIn('开启（种子 12345）',page)
            self.assertEqual(json.loads((run/'report/report_data.json').read_text())['sampling'],m['sampling'])

    def test_cpp_parser(self):
        # Compile the same parser the application uses, without initializing VIO.
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'main.cpp'; binary = Path(tmp)/'parser'
            source.write_text('''#include "VioCommandLine.hpp"
#include <iostream>
int main(int argc, char** argv) {
 try { auto o=okvis::parseVioCommandLine(argc,argv);
 std::cout << o.config << " " << o.dataset << " " << o.output << " " << o.rpg << " " << o.deterministic;
 return 0; } catch (...) { return 2; }
}''')
            subprocess.run(['c++','-std=c++17','-I'+str(ROOT/'okvis_apps/src'),str(source),'-o',str(binary)],check=True)
            cases = [(['c','d','out'],'c d out 0 0'), (['c','d','-rpg'],'c d d 1 0'),
                     (['c','d','out','-rpg'],'c d out 1 0'),
                     (['c','d','out','--deterministic'],'c d out 0 1'),
                     (['c','d','out','--deterministic','1'],'c d out 0 1'),
                     (['c','d','out','-rpg','--deterministic','0'],'c d out 1 0')]
            for args, expected in cases:
                self.assertEqual(subprocess.check_output([str(binary),*args],text=True),expected)
            for args in (['c'], ['c','d','out','extra'], ['c','d','--deterministic','2'],
                         ['c','d','--deterministic','true'], ['c','d','--unknown'],
                         ['c','d','--deterministic','--deterministic']):
                self.assertNotEqual(subprocess.run([str(binary),*args]).returncode,0)

if __name__ == '__main__': unittest.main()
