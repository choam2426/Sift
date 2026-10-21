import json
import pathlib
import tempfile
import unittest

import e2e


CASE = {
    'task_scope': 'test scope', 'mount': '/src/x', 'test_pkg': './pkg/x',
    'test_file_dir': 'pkg/x', 'question': 'Does this route check authorization?',
}


class TaskTests(unittest.TestCase):
    def test_question_is_symmetric(self):
        texts = [e2e.task(CASE, arm) for arm in ('vanilla', 'route-index', 'jev')]
        for text in texts:
            self.assertIn(CASE['question'], text)
        self.assertNotIn('Jev ranker', texts[0])
        self.assertIn('Jev ranker', texts[2])


class FinalizeTests(unittest.TestCase):
    def base(self, **kw):
        rec = {
            'total_cost_usd': 2.0,
            'jev': {'cost_usd': 0.1},
            'audit': {'docker': 0, 'network': 0, 'subagent': 0},
            'evaluation': {'verdict': 'reproduced', 'semantic_review': 'pending'},
            'cap_usd': 5.0,
        }
        rec.update(kw)
        return rec

    def test_semantic_pending_is_not_valid(self):
        rec = e2e.finalize_record(self.base(), 5.0)
        self.assertFalse(rec['valid'])
        self.assertTrue(rec['censored'])
        self.assertEqual(rec['cost_to_first_valid_usd'], 5.0)

    def test_accepted_is_valid(self):
        rec = self.base()
        rec['evaluation']['semantic_review'] = 'accepted'
        rec = e2e.finalize_record(rec, 5.0)
        self.assertTrue(rec['valid'])
        self.assertFalse(rec['censored'])
        self.assertEqual(rec['cost_to_first_valid_usd'], 2.1)

    def test_audit_invalidates(self):
        rec = self.base()
        rec['evaluation']['semantic_review'] = 'accepted'
        rec['audit']['docker'] = 1
        rec = e2e.finalize_record(rec, 5.0)
        self.assertFalse(rec['valid'])
        self.assertFalse(rec['audit_clean'])

    def test_over_cap_is_censored(self):
        rec = self.base(total_cost_usd=5.0)
        rec['evaluation']['semantic_review'] = 'accepted'
        rec = e2e.finalize_record(rec, 5.0)
        self.assertFalse(rec['valid'])
        self.assertFalse(rec['within_cap'])


class DecoyTests(unittest.TestCase):
    def test_decoy_is_a_code_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            target = root / 'pkg' / 'x'
            target.mkdir(parents=True)
            src = target / 'x.go'
            src.write_text('package x\n')
            e2e.add_decoy(root, CASE)
            self.assertIn('decoy', src.read_text())


if __name__ == '__main__':
    unittest.main()
