import os
import platform
import unittest

from openlcb.platformextras import SysDirs, clean_file_name


class TestPlatformExtras(unittest.TestCase):

    def test_clean_file_name(self):
        not_pathable_name = "hello:world"
        got_name = clean_file_name(not_pathable_name)
        self.assertEqual(got_name, "hello_world")

        got_name = clean_file_name(not_pathable_name, placeholder="-")
        self.assertEqual(got_name, "hello-world")

        with self.assertRaises(ValueError):
            _ = clean_file_name("contains_path{}not_just_file"
                                .format(os.path.sep))
        if os.path.sep != "/":
            with self.assertRaises(ValueError):
                # Manually check "/" since tkinter and possibly
                #   other Python modules insert "/" regardless of platform:
                _ = clean_file_name("contains_path{}not_just_file"
                                    .format("/"))

    def test_sysdirs(self):
        try_to_set_constant = "some value"
        with self.assertRaises(AttributeError):
            SysDirs.Cache = try_to_set_constant
        self.assertNotEqual(SysDirs.Cache, try_to_set_constant)

        self.assertIsInstance(SysDirs.Cache, str)
        if platform.system() == "Windows":
            self.assertGreater(len(SysDirs.Cache), 3)
            # ^ `>` instead of `>=`, since "C:/" would be bad & useless
            #   - same for "//" even if had folder (len("//x") == 3
            #     but is still bad): Disallow network folder for cache.
        else:
            self.assertGreater(len(SysDirs.Cache), 1)
            # ^ `>` instead of `>=`, since "/" would be bad & useless
            self.assertEqual(SysDirs.Cache[0], "/")  # ensure is absolute
            # - relative path to cache would be hard to find/clear
            # - even a path like "/t" is technically allowable for cache
            #   on unix-like os, though should be ~/.cache usually
        # Can't think of anything else to test, since
        #   SysDirs is the authority on the values
        #   (and result is platform-specific).
