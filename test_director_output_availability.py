import json
import unittest
from director_obs import ObsClient, OwnedOBS, ObsError, VirtualCameraUnavailable

class Wire:
    def __init__(self, status): self.status=status
    def settimeout(self, value): pass
    def send(self, raw): self.request=json.loads(raw)['d']
    def recv(self): return json.dumps({'op':7,'d':{**self.request,'requestStatus':self.status}})

class Outputs(unittest.TestCase):
    def client(self,status):
        c=ObsClient.__new__(ObsClient);c.ws=Wire(status);c.connected=True;c.audit=[];return c
    def test_exact_native_feature_absence(self):
        with self.assertRaises(VirtualCameraUnavailable): self.client({'result':False,'code':604,'comment':'VirtualCam is not available.'}).req('GetVirtualCamStatus')
    def test_other_refusals_stay_unknown(self):
        for code,comment in [(500,'VirtualCam is not available.'),(604,'Other error')]:
            with self.assertRaises(ObsError) as caught: self.client({'result':False,'code':code,'comment':comment}).req('GetVirtualCamStatus')
            self.assertNotIsInstance(caught.exception,VirtualCameraUnavailable)
    def native(self,value):
        class Client:
            def req(self,kind,data=None,timeout=3):
                if kind=='GetVirtualCamStatus' and value=='absent': raise VirtualCameraUnavailable()
                return {'outputActive': value if kind=='GetVirtualCamStatus' else False}
        return OwnedOBS(Client())
    def test_absence_is_explicit(self):
        n=self.native('absent');n.outputs_off();self.assertIsNone(n.output_states()['virtual_camera'])
    def test_active_refuses(self):
        with self.assertRaises(ObsError):self.native(True).outputs_off()
    def test_unknown_refuses(self):
        for value in [None,0,'false']:
            with self.assertRaises(ObsError):self.native(value).outputs_off()
    def test_real_false_passes(self): self.native(False).outputs_off()
if __name__=='__main__':unittest.main()
