"""Unit tests for py_path_component.core.

Tests are deterministic by construction: no wall-clock, no floats, no
network, no filesystem access. Every assertion targets behaviour the
implementation actually claims to support.
"""

import unittest

from py_path_component.core import (
    ComponentError,
    ValidationReport,
    validate_component,
    validate_path,
)


class TestValidateComponentWindows(unittest.TestCase):

    def test_simple_valid_name(self):
        r = validate_component("hello", os_name="windows")
        self.assertTrue(r.valid)
        self.assertEqual(r.errors, [])
        self.assertEqual(r.warnings, [])

    def test_reserved_con(self):
        r = validate_component("CON", os_name="windows")
        self.assertFalse(r.valid)
        self.assertTrue(any("reserved" in e for e in r.errors))

    def test_reserved_con_with_extension(self):
        r = validate_component("CON.txt", os_name="windows")
        self.assertFalse(r.valid)
        self.assertTrue(any("reserved" in e for e in r.errors))

    def test_reserved_lpt1_case_insensitive(self):
        r = validate_component("lpt1", os_name="windows")
        self.assertFalse(r.valid)
        self.assertTrue(any("reserved" in e for e in r.errors))

    def test_reserved_aux_with_log_extension(self):
        r = validate_component("AUX.log", os_name="windows")
        self.assertFalse(r.valid)
        self.assertTrue(any("reserved" in e for e in r.errors))

    def test_illegal_colon(self):
        r = validate_component("a:b", os_name="windows")
        self.assertFalse(r.valid)
        self.assertTrue(any("illegal" in e for e in r.errors))

    def test_illegal_question_mark(self):
        r = validate_component("what?", os_name="windows")
        self.assertFalse(r.valid)
        self.assertTrue(any("illegal" in e for e in r.errors))

    def test_trailing_space(self):
        r = validate_component("name ", os_name="windows")
        self.assertFalse(r.valid)
        self.assertTrue(any("space or dot" in e for e in r.errors))

    def test_trailing_dot(self):
        r = validate_component("name.", os_name="windows")
        self.assertFalse(r.valid)
        self.assertTrue(any("space or dot" in e for e in r.errors))

    def test_control_character(self):
        r = validate_component("name\x07", os_name="windows")
        self.assertFalse(r.valid)
        self.assertTrue(any("control" in e for e in r.errors))

    def test_case_folding_warning(self):
        r = validate_component("CamelCase", os_name="windows")
        self.assertTrue(r.valid)
        self.assertEqual(len(r.warnings), 1)
        self.assertIn("case", r.warnings[0].lower())

    def test_all_lowercase_no_warning(self):
        r = validate_component("lowername", os_name="windows")
        self.assertEqual(r.warnings, [])


class TestValidateComponentPosix(unittest.TestCase):

    def test_simple_valid_name(self):
        r = validate_component("hello", os_name="posix")
        self.assertTrue(r.valid)
        self.assertEqual(r.errors, [])
        self.assertEqual(r.warnings, [])

    def test_slash_is_error(self):
        r = validate_component("a/b", os_name="posix")
        self.assertFalse(r.valid)
        self.assertTrue(any("separator" in e for e in r.errors))

    def test_uppercase_is_fine_no_warning(self):
        r = validate_component("UPPER", os_name="posix")
        self.assertTrue(r.valid)
        self.assertEqual(r.warnings, [])

    def test_reserved_name_not_applied(self):
        r = validate_component("CON", os_name="posix")
        self.assertTrue(r.valid)


class TestUniversalRules(unittest.TestCase):

    def test_empty_is_invalid(self):
        r = validate_component("", os_name="posix")
        self.assertFalse(r.valid)
        self.assertTrue(any("empty" in e for e in r.errors))

    def test_nul_byte_is_illegal_everywhere(self):
        for osn in ("windows", "posix"):
            with self.subTest(os=osn):
                r = validate_component("a\x00b", os_name=osn)
                self.assertFalse(r.valid)
                self.assertTrue(any("NUL" in e for e in r.errors))

    def test_too_long_is_invalid(self):
        r = validate_component("x" * 300, os_name="posix")
        self.assertFalse(r.valid)
        self.assertTrue(any("exceeds" in e for e in r.errors))


class TestValidatePath(unittest.TestCase):

    def test_valid_posix_path(self):
        reports = validate_path("a/b/c", os_name="posix")
        self.assertEqual(len(reports), 3)
        self.assertTrue(all(rep.valid for rep in reports))

    def test_posix_path_with_empty_segment(self):
        reports = validate_path("a//b", os_name="posix")
        self.assertEqual(len(reports), 3)
        # The middle empty segment is invalid.
        self.assertFalse(reports[1].valid)

    def test_windows_path_backslash_split(self):
        reports = validate_path("a\\b\\c", os_name="windows")
        self.assertEqual(len(reports), 3)
        self.assertTrue(all(rep.valid for rep in reports))

    def test_windows_path_with_reserved_segment(self):
        reports = validate_path("good\\CON\\bad", os_name="windows")
        self.assertEqual(len(reports), 3)
        self.assertFalse(reports[1].valid)

    def test_returns_reports(self):
        reports = validate_path("a", os_name="posix")
        self.assertIsInstance(reports[0], ValidationReport)


class TestErrors(unittest.TestCase):

    def test_unsupported_os_raises(self):
        with self.assertRaises(ComponentError):
            validate_component("x", os_name="plan9")

    def test_non_string_component_raises(self):
        with self.assertRaises(ComponentError):
            validate_component(123, os_name="posix")  # type: ignore[arg-type]

    def test_non_string_path_raises(self):
        with self.assertRaises(ComponentError):
            validate_path(42, os_name="posix")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
