"""Write own test-profile INI files in OBS's exact grammar; no OBS startup.

Validation invokes only libobs config_* parser utilities. It never initializes
OBS, loads capture plugins, connects a socket, or changes OS permissions.
"""
import configparser
import subprocess
from pathlib import Path


def write_ini(path, sections):
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read_dict(sections)
    with Path(path).open('w') as stream:
        config.write(stream, space_around_delimiters=False)


def validate_ini(path, sections, checker):
    command = [str(Path(checker).resolve(strict=True)), str(Path(path))]
    for section, fields in sections.items():
        for key, expected in fields.items():
            command.extend((section, key, str(expected)))
    result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise ValueError('Own fixture INI rejected by the actual OBS parser')


AUDIO_SLOTS = ('DesktopAudioDevice1', 'DesktopAudioDevice2',
               'AuxAudioDevice1', 'AuxAudioDevice2', 'AuxAudioDevice3', 'AuxAudioDevice4')


def create_empty_fixture(root, checker):
    """Create a new, explicitly selected empty collection; never copy user state.

    OBS's Disabled audio-device UI clears the global source slots. In the saved
    collection those slots are absent/null; no capture-source object is created.
    These are not legacy INI device keys, which OBS 33 no longer reads here.
    """
    import json
    import uuid
    root = Path(root)
    root.mkdir(mode=0o700)  # refuse reuse
    config = root/'obs-studio'
    scenes = config/'basic/scenes'; scenes.mkdir(parents=True)
    profile = config/'basic/profiles/D5Fixture'; profile.mkdir(parents=True)
    output = root/'outputs'; output.mkdir()
    global_fields = {'General': {'MacOSPermissionsDialogLastShown': '1', 'EnableAutoUpdates': 'false'}}
    # OBS's fallback calls CreateDefaultScene(!FirstRun). True suppresses
    # CreateFirstRunSources (including default Mic/Aux) if collection loading fails.
    user_fields = {'General': {'FirstRun': 'true', 'ConfirmOnExit': 'false'},
                   'Basic': {'Profile': 'D5 Fixture', 'ProfileDir': 'D5Fixture',
                             'SceneCollection': 'Expanded Director', 'SceneCollectionFile': 'D5Empty.json'},
                   'BasicWindow': {'PreviewProgramMode': 'true', 'RecordWhenStreaming': 'false',
                                   'KeepRecordingWhenStreamStops': 'false'}}
    profile_fields = {'General': {'Name': 'D5 Fixture'},
                      'Video': {'BaseCX': '1920', 'BaseCY': '1080', 'OutputCX': '1920',
                                'OutputCY': '1080', 'FPSType': '0', 'FPSCommon': '30'},
                      'Audio': {'SampleRate': '48000', 'ChannelSetup': 'Stereo'},
                      'Output': {'Mode': 'Simple'},
                      'SimpleOutput': {'FilePath': str(output), 'RecRB': 'false'},
                      'AdvOut': {'RecFilePath': str(output), 'RecRB': 'false'}}
    for path, fields in [(config/'global.ini', global_fields), (config/'user.ini', user_fields),
                         (profile/'basic.ini', profile_fields)]:
        write_ini(path, fields)
        validate_ini(path, fields, checker)
    scene = {'name': 'Expanded Director', 'version': 2, 'groups': [], 'transitions': [],
             'current_scene': 'D5 Empty', 'current_program_scene': 'D5 Empty',
             'scene_order': [{'name': 'D5 Empty'}],
             'sources': [{'id': 'scene', 'versioned_id': 'scene', 'name': 'D5 Empty',
                          'uuid': str(uuid.uuid4()), 'settings': {'id_counter': 0, 'custom_size': False, 'items': []},
                          'mixers': 0, 'muted': True, 'monitoring_type': 0}]}
    scene.update({slot: None for slot in AUDIO_SLOTS})
    path = scenes/'D5Empty.json'
    path.write_text(json.dumps(scene, indent=2)+'\n')
    validate_empty_fixture(root, checker)
    return {'root': str(root), 'collection': 'Expanded Director', 'profile': 'D5 Fixture',
            'scene': str(path), 'launch_arguments': ['--collection', 'Expanded Director', '--profile', 'D5 Fixture'],
            'capture_inputs': 0, 'fallback_first_run': 'true; no default audio sources', 'global_audio_slots': 'all six disabled/null', 'replay_buffer': 'false in both output modes'}


def validate_empty_scene(path, checker):
    result = subprocess.run([str(Path(checker).resolve(strict=True)), '--scene', str(path)],
                            capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise ValueError('Own fixture scene rejected by the actual OBS JSON parser')


def validate_empty_fixture(root, checker):
    """Offline preflight, repeated immediately before any separately authorized launch.

    Do not trust values returned by the generator: reread the on-disk INI and
    collection through OBS's actual parsers. Missing/unreadable collections fail.
    FirstRun=true also prevents auto audio if a later OBS lookup still falls back.
    """
    config = Path(root)/'obs-studio'
    validate_ini(config/'user.ini',
                 {'General': {'FirstRun': 'true'},
                  'Basic': {'Profile': 'D5 Fixture', 'ProfileDir': 'D5Fixture',
                            'SceneCollection': 'Expanded Director',
                            'SceneCollectionFile': 'D5Empty.json'},
                  'BasicWindow': {'PreviewProgramMode': 'true'}}, checker)
    validate_empty_scene(config/'basic/scenes/D5Empty.json', checker)
