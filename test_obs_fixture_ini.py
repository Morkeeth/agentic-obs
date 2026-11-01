"""Actual OBS INI parser, never an app/device launch."""
import configparser
import json
import os
from pathlib import Path
import tempfile
import unittest
from tools.obs_fixture_ini import write_ini, validate_ini, create_empty_fixture, validate_empty_scene, validate_empty_fixture


class ObsFixtureIni(unittest.TestCase):
    def setUp(self):
        checker = os.environ.get('OBS_INI_CHECKER')
        if not checker or not Path(checker).is_file() or not os.access(checker, os.X_OK):
            reason = 'native prerequisites absent: OBS_INI_CHECKER must name an executable parser-only checker; see README native OBS checks'
            print('SKIP: '+reason, flush=True)
            self.skipTest(reason)

    def test_original_serializer_is_rejected_and_repaired_profile_is_recognized(self):
        fields = {'General': {'MacOSPermissionsDialogLastShown': '1'},
                  'Basic': {'SceneCollection': 'Expanded Director',
                            'SceneCollectionFile': 'Untitled.json', 'Profile': 'Untitled'}}
        with tempfile.TemporaryDirectory(prefix='obs-ini-parser-only-') as tmp:
            path = Path(tmp)/'fixture.ini'
            original = configparser.ConfigParser(); original.optionxform = str
            original.read_dict(fields)
            with path.open('w') as stream: original.write(stream)
            with self.assertRaises(ValueError):
                validate_ini(path, fields, os.environ['OBS_INI_CHECKER'])
            write_ini(path, fields)
            validate_ini(path, fields, os.environ['OBS_INI_CHECKER'])

    def test_fallback_disables_default_audio_source_creation(self):
        with tempfile.TemporaryDirectory(prefix='obs-fallback-offline-') as tmp:
            checker = os.environ['OBS_INI_CHECKER']
            root = Path(tmp)/'new'
            create_empty_fixture(root, checker)
            # OBS calls CreateDefaultScene(!FirstRun) if collection loading fails.
            validate_ini(root/'obs-studio/user.ini',
                         {'General': {'FirstRun': 'true'}}, checker)

    def test_preflight_rejects_first_run_false(self):
        with tempfile.TemporaryDirectory(prefix='obs-first-run-guard-offline-') as tmp:
            checker = os.environ['OBS_INI_CHECKER']
            root = Path(tmp)/'new'
            create_empty_fixture(root, checker)
            path = root/'obs-studio/user.ini'
            safe = path.read_text()
            self.assertIn('FirstRun=true', safe)
            path.write_text(safe.replace('FirstRun=true', 'FirstRun=false'))
            with self.assertRaises(ValueError):
                validate_empty_fixture(root, checker)
            path.write_text(safe)
            validate_empty_fixture(root, checker)

    def test_preflight_rejects_missing_collection(self):
        with tempfile.TemporaryDirectory(prefix='obs-missing-scene-offline-') as tmp:
            checker = os.environ['OBS_INI_CHECKER']
            root = Path(tmp)/'new'
            info = create_empty_fixture(root, checker)
            path = Path(info['scene'])
            safe = path.read_bytes()
            path.unlink()
            with self.assertRaises(ValueError):
                validate_empty_fixture(root, checker)
            path.write_bytes(safe)
            validate_empty_fixture(root, checker)

    def test_empty_collection_and_disabled_audio_are_checked_by_actual_obs_parser(self):
        with tempfile.TemporaryDirectory(prefix='obs-empty-fixture-offline-') as tmp:
            checker = os.environ['OBS_INI_CHECKER']
            root = Path(tmp)/'new'
            info = create_empty_fixture(root, checker)
            self.assertEqual(info['capture_inputs'], 0)
            path = Path(info['scene'])
            empty = json.loads(path.read_text())
            for slot in ('DesktopAudioDevice1', 'AuxAudioDevice1'):
                broken = dict(empty)
                broken[slot] = {'id': 'coreaudio_input_capture', 'settings': {'device_id': 'default'}}
                path.write_text(json.dumps(broken))
                with self.assertRaises(ValueError): validate_empty_scene(path, checker)
            broken = dict(empty)
            broken['sources'] = [{'id': 'coreaudio_input_capture'}]
            path.write_text(json.dumps(broken))
            with self.assertRaises(ValueError): validate_empty_scene(path, checker)
            path.write_text(json.dumps(empty))
            validate_empty_scene(path, checker)


if __name__ == '__main__': unittest.main()
