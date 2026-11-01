"""Actual arming decision; substitute only the cold renderer's arrival time."""
import tempfile,threading,unittest
from director import Director,ROOT
from director_simulator import SimulatedOBS
from test_director_cold_renderers import ColdRenderer
class ColdBudget(unittest.TestCase):
 def test_six_second_cold_renderer_can_arm_without_forged_readiness(self):
  with tempfile.TemporaryDirectory(dir=ROOT,prefix='.director-cold-budget-') as tmp,SimulatedOBS() as sim:
   d=Director(data_dir=tmp);done=threading.Event()
   def action(name,**kw):return d.execute({'action':name,**kw},d.version)
   action('connect',password=sim.password,port=sim.port);action('setup',fixtures=True);original=d.native.snapshot()
   def renderer():
    if done.wait(6):return
    with ColdRenderer(d,sim):done.wait(25)
   worker=threading.Thread(target=renderer);worker.start()
   try:
    action('arm',enabled=True);self.assertTrue(d.armed);self.assertEqual(d.native.snapshot(),original);self.assertFalse(d.agent_state()['agent_take_approved'])
   finally:done.set();worker.join(3);d.close()
if __name__=='__main__':unittest.main()
