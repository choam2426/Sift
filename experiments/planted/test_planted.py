#!/usr/bin/env python3
"""Offline tests for the Phase 2 harness pieces (no Docker, model, or network)."""
import pathlib, sys, tempfile, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
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


if __name__ == '__main__':
    unittest.main()
