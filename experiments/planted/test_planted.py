#!/usr/bin/env python3
"""Offline tests for the Phase 2 harness pieces (no Docker, model, or network)."""
import pathlib, sys, tempfile, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import analyze
import case as case_mod
import harness
import rank


SUITE_RUNNER = '''package api

func TestMessageSuite(t *testing.T) {
	suite.Run(t, new(MessageSuite))
}
'''


class SelectorTest(unittest.TestCase):
    def pkg(self, files):
        d = pathlib.Path(tempfile.mkdtemp())
        for name, text in files.items():
            (d / name).write_text(text)
        return d

    def test_top_level(self):
        groups = harness.selectors(self.pkg({}), 'func TestA(t *testing.T) {}\nfunc TestB(tt *testing.T) {}\nfunc helper() {}\n')
        self.assertEqual(groups, [('^(TestA|TestB)$', ['TestA', 'TestB'])])

    def test_suite_method_uses_existing_runner(self):
        d = self.pkg({'message_test.go': SUITE_RUNNER})
        groups = harness.selectors(d, 'func (s *MessageSuite) Test_X() {}\nfunc (s *MessageSuite) setup() {}\n')
        self.assertEqual(groups, [('^TestMessageSuite$/^(Test_X)$', ['TestMessageSuite/Test_X'])])

    def test_suite_method_with_runner_in_submission(self):
        text = 'func TestMine(t *testing.T) {\n\tsuite.Run(t, &MySuite{})\n}\nfunc (s MySuite) TestY() {}\n'
        groups = harness.selectors(self.pkg({}), text)
        # the runner is itself a top-level test, so it runs every method; no extra group
        self.assertEqual(groups, [('^(TestMine)$', ['TestMine'])])

    def test_suite_without_runner_is_not_runnable(self):
        self.assertEqual(harness.selectors(self.pkg({}), 'func (s *Lost) TestZ() {}\n'), [])


class StripNamesTest(unittest.TestCase):
    def test_maps_subtests_to_methods_and_tops(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / 'pkg').mkdir()
        (d / 'pkg' / 'a_test.go').write_text(SUITE_RUNNER + 'func (s *MessageSuite) Test_Owned() {}\nfunc TestPlain(t *testing.T) {}\n')
        names = case_mod.strip_names(d, 'pkg', ['TestMessageSuite', 'TestMessageSuite/Test_Owned', 'TestPlain', 'TestPlain/case_1'])
        # the suite runner is kept because a method was removed instead
        self.assertEqual(names, ['TestPlain', 'Test_Owned'])


class RankTest(unittest.TestCase):
    def test_tokens_split_identifiers(self):
        self.assertEqual(rank.tokens('CanWriteRepo userID'), ['can', 'write', 'repo', 'user', 'id'])

    def test_bm25_prefers_matching_unit(self):
        units = [{'target': 'a.go', 'text': 'func Render() { draw() }'},
                 {'target': 'b.go', 'text': 'func checkAuthorization(caller) { if !caller.CanAccess(resource) { deny() } }'}]
        s = rank.bm25(units, rank.QUESTION)
        self.assertGreater(s[1], s[0])


class InfraAbortTest(unittest.TestCase):
    def test_session_limit_is_infra(self):
        main = {'is_error': True, 'terminal_reason': 'api_error', 'result': "You've hit your session limit · resets 8:40pm"}
        self.assertIn('session limit', harness.infra_abort(main))

    def test_normal_completion_is_not(self):
        self.assertIsNone(harness.infra_abort({'is_error': False, 'terminal_reason': 'completed', 'result': 'done'}))

    def test_budget_stop_is_not(self):
        # hitting --max-budget-usd is the agent's outcome under the cap, not an infra failure
        self.assertIsNone(harness.infra_abort({'is_error': True, 'subtype': 'error_max_budget_usd', 'terminal_reason': 'budget_exhausted', 'result': 'None'}))


class AnalyzeTest(unittest.TestCase):
    def test_ratio_uses_mean_cost_including_invalid_runs(self):
        cases = {'c1': {'vanilla': [{'cost': 4.0}, {'cost': 2.0}], 'rank-jev': [{'cost': 1.5}, {'cost': 1.5}]}}
        self.assertAlmostEqual(analyze.ratio(cases, 'rank-jev', 'vanilla')['c1'], 0.5)

    def test_verdict(self):
        self.assertEqual(analyze.verdict(0.8, 0.95, 0.90), 'supported')
        self.assertEqual(analyze.verdict(0.8, 1.05, 0.90), 'inconclusive')
        self.assertEqual(analyze.verdict(1.0, 1.2, 0.90), 'refuted')

    def test_bootstrap_moves_repo_cases_together(self):
        ratios = {'a1': 0.5, 'a2': 0.5, 'b1': 2.0}
        lo, hi = analyze.boot_geomean(ratios, {'a1': 'a', 'a2': 'a', 'b1': 'b'})
        self.assertLessEqual(lo, 0.5 + 1e-9)
        self.assertGreaterEqual(hi, 2.0 - 1e-9)

    def test_slope(self):
        self.assertAlmostEqual(analyze.slope([(0, 0), (1, -1), (2, -2)]), -1.0)


if __name__ == '__main__':
    unittest.main()
