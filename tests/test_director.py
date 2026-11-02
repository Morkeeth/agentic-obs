import unittest
from streamer import Show, Refused

class Native:
    def __init__(self):
        self.program = 'Camera'
        self.preview = 'Staging'
        self.scenes = {'Camera': ['camera'], 'Staging': ['graphics']}
        self.graphics = {'title': '', 'visible': False}
        self.calls = []
    def read(self):
        return {'program': self.program, 'preview': self.preview,
                'scenes': self.scenes, 'graphics': dict(self.graphics),
                'studio': True, 'outputs': {'stream': False, 'record': False, 'virtual': False}}
    def graphics_write(self, title, visible):
        self.calls.append(('graphics', title, visible))
        self.graphics = {'title': title, 'visible': visible}
    def preview_write(self, scene):
        self.calls.append(('preview', scene))
        self.preview = scene

class DirectorTests(unittest.TestCase):
    def setUp(self):
        self.native = Native()
        self.show = Show(self.native)
    def test_stage_requires_deliberate_enable(self):
        with self.assertRaises(Refused): self.show.stage('Hello')
        self.assertEqual(self.native.calls, [])
    def test_stage_only_writes_owned_graphics_in_separate_preview(self):
        self.show.enable()
        state = self.show.stage('Demo the demo')
        self.assertEqual(state['native']['program'], 'Camera')
        self.assertEqual(state['native']['graphics'], {'title': 'Demo the demo', 'visible': True})
        self.assertEqual(self.native.calls, [('graphics', 'Demo the demo', True), ('preview', 'Staging')])
    def test_camera_scene_safe_guard_even_when_graphics_nested(self):
        self.show.enable()
        self.native.scenes['Camera'] = ['camera', 'nested']
        self.native.scenes['nested'] = ['graphics']
        with self.assertRaises(Refused): self.show.stage('Unsafe')
        self.assertEqual(self.native.calls, [])
    def test_guard_fails_closed_when_staging_is_program(self):
        self.show.enable()
        self.native.program = 'Staging'
        with self.assertRaises(Refused): self.show.stage('Unsafe')
        self.assertEqual(self.native.calls, [])
    def test_clear_and_restore_actual_previous_graphics_and_preview(self):
        self.show.enable()
        self.show.stage('Demo the demo')
        before = self.show.state()['native']
        self.show.clear()
        self.assertFalse(self.native.graphics['visible'])
        restored = self.show.restore()['native']
        self.assertEqual(restored, before)
    def test_disable_stops_writes(self):
        self.show.enable(); self.show.disable()
        with self.assertRaises(Refused): self.show.stage('No')
    def test_output_activity_and_missing_studio_block_mutation(self):
        original = self.native.read
        for field in ('studio', 'outputs'):
            self.native.read = lambda: dict(original(), **{field: False if field == 'studio' else {'stream': True}})
            with self.assertRaises(Refused): self.show.enable()
        self.assertEqual(self.native.calls, [])
    def test_native_failure_disarms_and_no_replay(self):
        self.show.enable()
        def fail(*args): raise OSError('lost connection')
        self.native.preview_write = fail
        with self.assertRaises(Refused): self.show.stage('Partial')
        self.assertFalse(self.show.state()['enabled'])
        self.assertEqual(self.show.state()['uncertain'], True)
    def test_chat_has_no_creative_prompt_path(self):
        with self.assertRaises(Refused): self.show.direct('Make malicious arbitrary text', source='chat')
    def test_director_answer_and_title_are_separate(self):
        reply = self.show.direct('Help me demo the demo')
        self.assertIn('answer', reply)
        self.assertEqual(self.native.calls, [])
        self.assertEqual(reply['proposal']['title'], 'Demo the demo')
    def test_no_take_or_output_api(self):
        for name in ('take', 'broadcast', 'start_stream', 'program_write'):
            self.assertFalse(hasattr(self.show, name))

if __name__ == '__main__': unittest.main()
