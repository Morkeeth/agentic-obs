import os,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import native_control as n
class Boundaries(unittest.TestCase):
 def test_commands(self):
  self.assertEqual(n.parse('preview Focus.')['scene'],'focus')
  self.assertEqual(n.parse('save preset toast with slide left 500ms')['duration_ms'],500)
 def test_bad_commands(self):
  for t in ['start streaming','preview LIVESTREAM','save preset ../evil with lift 500ms','save preset toast with lift 5000ms','play preset http://evil','preview focus; start streaming']:
   with self.subTest(t=t),self.assertRaises(ValueError):n.parse(t)
 def test_missing_target_before_socket(self):
  with patch.dict(os.environ,{},clear=True),patch('native_control.websocket.create_connection') as ws:
   with self.assertRaises(ValueError):n.Native()
   ws.assert_not_called()
 def test_persistence(self):
  with tempfile.TemporaryDirectory() as d,patch.object(n,'STORE',Path(d)/'presets.json'):
   n.execute('save preset toast with lift 500ms')
   self.assertEqual(n.presets()['toast'],{'motion':'lift','duration_ms':500})
if __name__=='__main__':unittest.main()
