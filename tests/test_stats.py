"""Stats tests: the README's intervals and z-scores come from this code."""
import unittest

from game.stats import two_proportion_z, wilson_interval


class TestWilsonInterval(unittest.TestCase):
    def test_matches_the_readme_boss_row(self):
        # 33/60 (55%) -> 42.5%..66.9%, 12/60 (20%) -> 11.8%..31.8%
        lo, hi = wilson_interval(33, 60)
        self.assertEqual((round(lo, 3), round(hi, 3)), (0.425, 0.669))
        lo, hi = wilson_interval(12, 60)
        self.assertEqual((round(lo, 3), round(hi, 3)), (0.118, 0.318))

    def test_perfect_record_keeps_a_real_lower_bound(self):
        lo, hi = wilson_interval(60, 60)
        self.assertEqual(hi, 1.0)
        self.assertAlmostEqual(lo, 0.940, places=3)

    def test_zero_record_is_bounded_at_zero(self):
        lo, hi = wilson_interval(0, 60)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.060, places=3)

    def test_rejects_empty_sample(self):
        with self.assertRaises(ValueError):
            wilson_interval(0, 0)


class TestTwoProportionZ(unittest.TestCase):
    def test_matches_the_readme(self):
        # boss: mcts 33/60 vs random 12/60; duel: mcts 60/60 vs random 54/60
        self.assertEqual(round(two_proportion_z(33, 60, 12, 60), 2), 3.96)
        self.assertEqual(round(two_proportion_z(60, 60, 54, 60), 2), 2.51)

    def test_sign_follows_the_argument_order(self):
        self.assertLess(two_proportion_z(12, 60, 33, 60), 0.0)

    def test_identical_extremes_are_zero_not_nan(self):
        self.assertEqual(two_proportion_z(60, 60, 60, 60), 0.0)
        self.assertEqual(two_proportion_z(0, 60, 0, 60), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
