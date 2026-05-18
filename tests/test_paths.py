"""Tests for alias path normalization (security + consistency)."""

from __future__ import annotations

import unittest

from asset_store_core import ValidationError, normalize_relative_alias, normalize_space, qualified_alias


class PathsTest(unittest.TestCase):
    def test_qualified_alias_normalizes_slashes(self) -> None:
        self.assertEqual(
            "cache/bnf/example.jpg",
            qualified_alias(" cache/ ", "/bnf/example.jpg/"),
        )

    def test_rejects_empty_components(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_space("")
        with self.assertRaises(ValidationError):
            normalize_relative_alias("")
        with self.assertRaises(ValidationError):
            normalize_relative_alias("a//b")

    def test_rejects_dot_segments(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_relative_alias("..")
        with self.assertRaises(ValidationError):
            normalize_relative_alias("a/../b")

    def test_space_must_be_single_segment(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_space("u-42/extra")


if __name__ == "__main__":
    unittest.main()
