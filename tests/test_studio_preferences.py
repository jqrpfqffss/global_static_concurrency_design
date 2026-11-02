from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ecra.human_reviews import ReviewStore
from ecra.report_package import sha256
from ecra.scan_store import EvidenceProvider, publish_scan
from ecra.studio.server import create_app
from ecra import studio_preferences as prefs
from ecra.workspace import user_data_root, default_user_data_root


class StudioPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ecra 目录设置 ')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,LOCALAPPDATA=str(self.root/'user'),XDG_CONFIG_HOME=str(self.root/'settings'),
                            XDG_DATA_HOME=str(self.root/'default'),ECRA_DATA_ROOT='')
        self.env.start();self.addCleanup(self.env.stop)
        self.current=self.root/'current';self.current.mkdir()
        self.target=self.root/'新数据 根'

    def save(self,target=None,**extra):
        target=target or self.target;plan=prefs.preview(str(target),self.current)
        return prefs.save(str(target),self.current,plan_id=plan['plan_id'],revision=plan['revision'],**extra)

    def raw(self):
        file=prefs.preference_home()/'preferences.json'
        return file.read_bytes() if file.exists() else None

    def test_original_system_default_no_preferences_side_effect_and_preview_is_readonly(self):
        self.assertEqual(user_data_root(),default_user_data_root())
        home=prefs.preference_home();self.assertFalse(home.exists())
        plan=prefs.preview(str(self.target),self.current)
        self.assertEqual(plan['kind'],'EMPTY');self.assertFalse(self.target.exists());self.assertFalse(home.exists())
        self.assertEqual(prefs.startup_selection()['source'],'SYSTEM_DEFAULT')

    def test_explicit_save_next_start_and_unknown_preferences_fields_preserved_with_exact_backup(self):
        first=self.save();self.assertTrue(first['saved'])
        self.assertEqual(user_data_root(),self.target.resolve());self.assertEqual(list(self.target.iterdir()),[])
        file=prefs.preference_home()/'preferences.json';payload=json.loads(file.read_bytes());payload['future']={'keep':[True,'原文']}
        file.write_text(json.dumps(payload,ensure_ascii=False),'utf-8');old=file.read_bytes()
        other=self.root/'另一个数据';self.save(other)
        self.assertEqual(json.loads(file.read_bytes())['future'],payload['future'])
        backup=prefs.preference_home()/'preferences-backups'/(hashlib.sha256(old).hexdigest()+'.json')
        self.assertEqual(backup.read_bytes(),old);self.assertEqual(user_data_root(),other.resolve())
        self.assertEqual(list(self.current.iterdir()),[])

    def test_argument_and_environment_precede_saved_default_even_when_preferences_corrupt(self):
        self.save();file=prefs.preference_home()/'preferences.json';file.write_bytes(b'corrupt setting')
        environment=self.root/'env';argument=self.root/'arg'
        with patch.dict(os.environ,ECRA_DATA_ROOT=str(environment)):
            self.assertEqual(user_data_root(),environment.resolve())
            self.assertEqual(prefs.startup_selection()['source'],'ENVIRONMENT')
            self.assertEqual(prefs.startup_selection(argument)['root'],argument.resolve())
            self.assertEqual(prefs.startup_selection(argument)['source'],'STARTUP_ARGUMENT')
        with self.assertRaises(prefs.PreferenceError):user_data_root()
        self.assertEqual(prefs.startup_selection()['source'],'RECOVERY_DEFAULT')
        self.assertEqual(file.read_bytes(),b'corrupt setting')

    def test_registered_archive_and_human_events_survive_default_restart(self):
        app=create_app(self.target,token='root-test',authority='127.0.0.1:12345')
        with TestClient(app,base_url='http://127.0.0.1:12345'):pass
        folder=self.target/'scans/saved';folder.mkdir(parents=True)
        publish_scan(folder/'scan.db',dict(variables=[dict(symbol_id='id',name='counter',static_classification='UNKNOWN')]),{},scan_id='saved',project_id='p')
        provider=EvidenceProvider(folder/'scan.db');reviews=ReviewStore(folder/'reviews.db',provider.metadata())
        event=reviews.append('id',provider.fingerprint('id'),reviewer='目录验收声明',decision='NEED_MORE_EVIDENCE')
        before=sha256(folder/'scan.db');self.save()
        app=create_app(token='root-test',authority='127.0.0.1:12345')
        with TestClient(app,base_url='http://127.0.0.1:12345',headers={'X-ECRA-Session':'root-test'}) as client:
            bootstrap=client.get('/api/bootstrap').json();self.assertEqual(bootstrap['data_root'],str(self.target.resolve()))
            self.assertEqual(bootstrap['data_root_source'],'GUI_DEFAULT')
            self.assertEqual(client.get('/api/scans').json()['items'][0]['scan_id'],'saved')
        self.assertEqual(reviews.history()[0]['event_id'],event['event_id']);self.assertEqual(sha256(folder/'scan.db'),before)

    def test_invalid_source_install_nested_drive_and_nonempty_targets_do_not_create_preferences(self):
        fw=self.root/'firmware';fw.mkdir()
        profile=self.current/'projects/p/profiles/main.yaml';profile.parent.mkdir(parents=True)
        profile.write_text(json.dumps(dict(version=1,project=dict(root=str(fw)))),'utf-8')
        ordinary=self.root/'ordinary';ordinary.mkdir();(ordinary/'keep.txt').write_text('preserve','utf-8')
        from ecra.config import TOOL_ROOT
        paths=['relative',str(Path(self.root.anchor)),str(TOOL_ROOT/'data'),str(self.current/'nested'),str(self.current.parent),str(fw),str(fw/'data'),str(ordinary)]
        before=profile.read_bytes()
        for target in paths:
            with self.subTest(target=target),self.assertRaises(ValueError):prefs.preview(target,self.current)
        self.assertIsNone(self.raw());self.assertEqual(list(fw.iterdir()),[]);self.assertEqual(profile.read_bytes(),before)
        self.assertEqual((ordinary/'keep.txt').read_text('utf-8'),'preserve')

    def test_actual_directory_link_rejected_without_touching_referent(self):
        target=self.root/'referent';target.mkdir()
        link=self.root/'linked';os.symlink(target,link,target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError,'链接|Junction'):prefs.preview(str(link),self.current)
            self.assertEqual(list(target.iterdir()),[]);self.assertIsNone(self.raw())
        finally:link.unlink()

    def test_stale_revision_rejected_without_last_writer_wins(self):
        one=prefs.preview(str(self.target),self.current)
        other=self.root/'other';two=prefs.preview(str(other),self.current)
        prefs.save(str(self.target),self.current,plan_id=one['plan_id'],revision=one['revision'])
        original=self.raw()
        with self.assertRaises(prefs.PreferenceConflict):
            prefs.save(str(other),self.current,plan_id=two['plan_id'],revision=two['revision'])
        self.assertEqual(self.raw(),original);self.assertFalse(other.exists())

    def test_real_held_settings_lock_reports_conflict_without_creating_target(self):
        from ecra.storage_activity import DataActivity
        plan=prefs.preview(str(self.target),self.current)
        with DataActivity(prefs.preference_home(),exclusive=True):
            with self.assertRaises(prefs.PreferenceConflict):
                prefs.save(str(self.target),self.current,plan_id=plan['plan_id'],revision=plan['revision'])
        self.assertIsNone(self.raw());self.assertFalse(self.target.exists())

    def test_manually_edited_program_ancestor_preference_is_not_used_for_startup(self):
        from ecra.config import TOOL_ROOT
        file=prefs.preference_home()/'preferences.json';file.parent.mkdir(parents=True)
        raw=json.dumps(dict(format='ECRA_STUDIO_PREFERENCES',version=1,data_root=str(Path(TOOL_ROOT).parent))).encode()
        file.write_bytes(raw)
        self.assertEqual(prefs.startup_selection()['source'],'RECOVERY_DEFAULT')
        self.assertEqual(file.read_bytes(),raw)

    def test_preview_target_ownership_change_requires_new_preview(self):
        app=create_app(self.target,token='test',authority='127.0.0.1:12345')
        with TestClient(app,base_url='http://127.0.0.1:12345'):pass
        plan=prefs.preview(str(self.target),self.current)
        marker=self.target/'settings/device.json';marker.write_text(json.dumps(dict(device='device-changed')),'utf-8')
        with self.assertRaises(prefs.PreferenceConflict):
            prefs.save(str(self.target),self.current,plan_id=plan['plan_id'],revision=plan['revision'])
        self.assertIsNone(self.raw())

    def test_corrupt_settings_recovery_requires_explicit_backup_then_repairs(self):
        file=prefs.preference_home()/'preferences.json';file.parent.mkdir(parents=True);raw=b'{corrupt\n';file.write_bytes(raw)
        app=create_app(token='test',authority='127.0.0.1:12345')
        with TestClient(app,base_url='http://127.0.0.1:12345',headers={'X-ECRA-Session':'test'}) as client:
            boot=client.get('/api/bootstrap').json();self.assertEqual(boot['data_root_source'],'RECOVERY_DEFAULT');self.assertIn('恢复设置',boot['preference_warning'])
        with self.assertRaisesRegex(ValueError,'备份损坏'):self.save()
        self.assertEqual(file.read_bytes(),raw)
        self.save(repair=True)
        backup=file.parent/'preferences-backups'/(hashlib.sha256(raw).hexdigest()+'.json')
        self.assertEqual(backup.read_bytes(),raw);self.assertEqual(user_data_root(),self.target.resolve())

    def test_unusable_saved_data_root_opens_explicit_recovery_without_rewriting_marker(self):
        self.save();(self.target/'settings').mkdir();marker=self.target/'settings/device.json';marker.write_bytes(b'broken')
        app=create_app(token='test',authority='127.0.0.1:12345')
        with TestClient(app,base_url='http://127.0.0.1:12345',headers={'X-ECRA-Session':'test'}) as client:
            value=client.get('/api/bootstrap').json();self.assertEqual(value['data_root_source'],'RECOVERY_DEFAULT')
            self.assertIn('已保存目录无法打开',value['preference_warning'])
        self.assertEqual(marker.read_bytes(),b'broken')

    def test_probe_and_atomic_replace_failure_keep_old_preference_and_no_pending_file(self):
        self.save();before=self.raw();other=self.root/'other'
        plan=prefs.preview(str(other),self.current)
        with patch('ecra.studio_preferences.tempfile.TemporaryFile',side_effect=PermissionError('controlled readonly')):
            with self.assertRaises(PermissionError):prefs.save(str(other),self.current,plan_id=plan['plan_id'],revision=plan['revision'])
        self.assertEqual(self.raw(),before)
        plan=prefs.preview(str(other),self.current)
        with patch('ecra.common.replace_file',side_effect=OSError('controlled write failure')):
            with self.assertRaises(OSError):prefs.save(str(other),self.current,plan_id=plan['plan_id'],revision=plan['revision'])
        self.assertEqual(self.raw(),before);self.assertFalse(list(prefs.preference_home().glob('*.pending')))

    def test_api_auth_origin_and_conflicting_revision(self):
        app=create_app(self.current,token='root-token',authority='127.0.0.1:12345')
        with TestClient(app,base_url='http://127.0.0.1:12345') as client:
            base='/api/settings/data-root'
            self.assertEqual(client.get(base).status_code,401)
            headers={'X-ECRA-Session':'root-token'}
            self.assertEqual(client.get(base,headers={**headers,'Host':'other'}).status_code,403)
            self.assertEqual(client.post(base+'/preview',headers=headers,json=dict(path=str(self.target))).status_code,403)
            headers['Origin']='http://127.0.0.1:12345'
            current=client.get(base,headers=headers).json();self.assertEqual(current['source'],'STARTUP_ARGUMENT')
            value=client.post(base+'/preview',headers=headers,json=dict(path=str(self.target))).json()
            payload=dict(path=value['path'],plan_id=value['plan_id'],revision=value['revision'])
            self.assertEqual(client.put(base,headers=headers,json=payload).status_code,200)
            self.assertEqual(client.put(base,headers=headers,json=payload).status_code,409)
            self.assertEqual(client.get('/api/bootstrap',headers=headers).json()['data_root'],str(self.current.resolve()))


if __name__=='__main__':unittest.main()
