"""Invalid demo limits are usage errors before scenario or search side effects."""
import contextlib
import io
import unittest
from unittest.mock import Mock, patch

import demo


class DemoArgumentTests(unittest.TestCase):
    def test_invalid_limits_refuse_before_creating_or_printing_a_scenario(self):
        cases = ((["--sims", "-1"], "--sims must be nonnegative"),
                 (["--budget-ms", "-1"], "--budget-ms must be nonnegative"),
                 (["--horizon", "0"], "--horizon must be positive"),
                 (["--horizon", "-2", "--sims", "0"], "--horizon must be positive"))
        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                scenario = Mock(side_effect=AssertionError(
                    "invalid limits created a scenario"))
                out, err = io.StringIO(), io.StringIO()
                with (patch("demo.SCENARIOS", {"boss": scenario}),
                      patch("demo.MCTS") as search,
                      patch("demo.show_one_round") as reference,
                      patch("sys.argv", ["demo.py", *arguments]),
                      contextlib.redirect_stdout(out), contextlib.redirect_stderr(err),
                      self.assertRaises(SystemExit) as caught):
                    demo.main()
                self.assertEqual(caught.exception.code, 2)
                self.assertIn("usage:", err.getvalue())
                self.assertIn(message, err.getvalue())
                self.assertNotIn("Traceback", err.getvalue())
                self.assertEqual(out.getvalue(), "")
                scenario.assert_not_called()
                search.assert_not_called()
                reference.assert_not_called()

    def test_fixed_count_still_ignores_an_unused_negative_clock_budget(self):
        out = io.StringIO()
        with (patch("sys.argv", ["demo.py", "duel", "--sims", "0",
                                 "--budget-ms", "-1"]),
              contextlib.redirect_stdout(out)):
            demo.main()
        self.assertIn("0 simulations", out.getvalue())
        self.assertIn("no recommendation is available", out.getvalue())


if __name__ == "__main__":
    unittest.main()
