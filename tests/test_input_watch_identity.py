"""Real Windows directory identity interleavings and registration rollback."""
import ctypes
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from ecra.guarded_cmake import InputWatch,require_protected_source


@unittest.skipUnless(os.name=='nt','Actual Windows directory handles required')
class InputWatchIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA-Q207-identity-');self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name).resolve()
        self.assertEqual(self.home.parent,Path(tempfile.gettempdir()).resolve())
        self.outer=self.home/'outer';self.source=self.outer/'source';self.source.mkdir(parents=True)
        (self.source/'main.c').write_bytes(b'int shared;\n')
        self.replacement=self.home/'replacement';self.replacement.mkdir()
        (self.replacement/'main.c').write_bytes(b'int shared;\n')
        require_protected_source(self.source)

    def changed_and_restored(self,path):
        raw=path.read_bytes();stamp=path.stat()
        path.write_bytes(b'int changed;\n');path.write_bytes(raw)
        os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))

    def test_root_swap_after_real_notification_registration_is_blocked(self):
        backup=self.home/'source-original';record=[]
        with InputWatch() as watch:
            original=watch.api.FindFirstChangeNotificationW
            def registered(path,subtree,mask):
                handle=original(path,subtree,mask);self.assertEqual(mask,287)
                try:self.source.rename(backup);self.replacement.rename(self.source)
                except OSError:record.append('BLOCKED')
                else:record.append('SWAPPED')
                return handle
            watch.api.FindFirstChangeNotificationW=registered
            watch.directory(self.source);require_protected_source(self.source);watch.check()
            self.assertEqual(record,['BLOCKED'])
            self.changed_and_restored(self.source/'main.c')
            with self.assertRaisesRegex(ValueError,'CMake输入目录.*变化'):watch.check()

    def test_ancestor_is_locked_before_target_handle_is_opened(self):
        replacement_outer=self.home/'replacement-outer';(replacement_outer/'source').mkdir(parents=True)
        (replacement_outer/'source/main.c').write_bytes(b'int shared;\n')
        backup=self.home/'outer-original';record=[]
        with InputWatch() as watch:
            original=watch.api.CreateFileW
            def create(path,access,*args):
                if Path(path)==self.source and access==0x80000000 and not record:
                    try:self.outer.rename(backup);replacement_outer.rename(self.outer)
                    except OSError:record.append('BLOCKED')
                    else:record.append('SWAPPED')
                return original(path,access,*args)
            watch.api.CreateFileW=create
            watch.directory(self.source);watch.check()
            self.assertEqual(record,['BLOCKED'])
            self.changed_and_restored(self.source/'main.c')
            with self.assertRaisesRegex(ValueError,'CMake输入目录.*变化'):watch.check()

    def shared_watch(self,watch):
        existing=self.home/'existing';existing.mkdir();(existing/'old.c').write_bytes(b'int old;\n')
        watch.directory(existing)
        return existing,set(watch.ancestors),dict(watch.ancestor_ids),dict(watch.directories)

    def assert_transaction_released_only_new(self,watch,saved):
        existing,ancestors,identities,directories=saved
        self.assertEqual(set(watch.ancestors),ancestors);self.assertEqual(watch.ancestor_ids,identities)
        self.assertEqual(watch.directories,directories)
        renamed=self.home/'failed-source-renamed';self.source.rename(renamed);renamed.rename(self.source)
        with self.assertRaises(OSError):existing.rename(self.home/'must-still-be-locked')
        watch.check()

    def test_create_file_failure_releases_new_handles_but_keeps_existing_watch(self):
        with InputWatch() as watch:
            saved=self.shared_watch(watch);original=watch.api.CreateFileW
            def create(path,access,*args):
                if Path(path)==self.source and access==0x80000000:
                    ctypes.set_last_error(5);return ctypes.c_void_p(-1).value
                return original(path,access,*args)
            watch.api.CreateFileW=create
            with self.assertRaises(OSError):watch.directory(self.source)
            watch.api.CreateFileW=original
            self.assert_transaction_released_only_new(watch,saved)

    def test_notification_failure_releases_new_handles_but_keeps_existing_watch(self):
        with InputWatch() as watch:
            saved=self.shared_watch(watch);original=watch.api.FindFirstChangeNotificationW
            def fail(*args):ctypes.set_last_error(5);return ctypes.c_void_p(-1).value
            watch.api.FindFirstChangeNotificationW=fail
            with self.assertRaises(OSError):watch.directory(self.source)
            watch.api.FindFirstChangeNotificationW=original
            self.assert_transaction_released_only_new(watch,saved)

    def test_identity_api_failure_after_registration_closes_real_notification(self):
        with InputWatch() as watch:
            saved=self.shared_watch(watch)
            native_find=watch.api.FindFirstChangeNotificationW;native_info=watch.api.GetFileInformationByHandle
            notifications=[]
            def find(*args):
                handle=native_find(*args);notifications.append(handle);return handle
            def info(*args):
                if notifications:ctypes.set_last_error(5);return False
                return native_info(*args)
            watch.api.FindFirstChangeNotificationW=find;watch.api.GetFileInformationByHandle=info
            with self.assertRaises(OSError):watch.directory(self.source)
            watch.api.FindFirstChangeNotificationW=native_find;watch.api.GetFileInformationByHandle=native_info
            self.assertEqual(len(notifications),1)
            self.assertEqual(watch.api.WaitForSingleObject(notifications[0],0),-1)
            self.assert_transaction_released_only_new(watch,saved)

    def test_stop_after_registration_rolls_back_only_new_resources(self):
        with InputWatch() as watch:
            saved=self.shared_watch(watch)
            with patch('ecra.scan_stop.check_stop',side_effect=KeyboardInterrupt('actual stop boundary')):
                with self.assertRaises(KeyboardInterrupt):watch.directory(self.source)
            self.assert_transaction_released_only_new(watch,saved)
        self.assertFalse(watch.directories);self.assertFalse(watch.ancestors);self.assertFalse(watch.ancestor_ids)

    def test_replacement_junction_before_target_lock_is_rejected(self):
        backup=self.home/'source-before-junction';created=[]
        with InputWatch() as watch:
            original=watch.api.CreateFileW
            def create(path,access,*args):
                if Path(path)==self.source and access==0x80000000 and not created:
                    self.source.rename(backup)
                    result=subprocess.run(['cmd','/c','mklink','/J',str(self.source),str(self.replacement)],capture_output=True)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr);created.append(True)
                return original(path,access,*args)
            watch.api.CreateFileW=create
            try:
                with self.assertRaisesRegex(ValueError,'重解析'):watch.directory(self.source)
            finally:
                watch.api.CreateFileW=original
                if created:
                    self.assertTrue(self.source.absolute().is_relative_to(self.home))
                    self.assertTrue(self.source.resolve().is_relative_to(self.home))
                    os.rmdir(self.source)  # remove only our junction, never its target
                    backup.rename(self.source)
            self.assertFalse(watch.directories);self.assertFalse(watch.ancestors)


if __name__=='__main__':unittest.main()
