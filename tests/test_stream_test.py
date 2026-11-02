import copy,unittest
from streamer import Refused
from stream_test import StreamTest

class Wire:
    def __init__(self):
        self.calls=[];self.active=False;self.data={'streamServiceType':'rtmp_common','streamServiceSettings':{'service':'Twitch','server':'rtmp://live.twitch.tv/app','key':'live_'+('sample'*8),'other':'preserved'}}
    def request(self,method,data=None):
        self.calls.append(method)
        if method in ('GetStreamStatus','GetRecordStatus','GetVirtualCamStatus'):return {'outputActive':self.active}
        if method=='GetStreamServiceSettings':return copy.deepcopy(self.data)
        if method=='SetStreamServiceSettings':self.data=copy.deepcopy(data);return {}
        raise AssertionError(method)

class StreamTests(unittest.TestCase):
    def test_prepares_existing_twitch_key_without_exposing_it_or_starting_outputs(self):
        w=Wire();s=StreamTest(w);r=s.prepare();self.assertTrue(w.data['streamServiceSettings']['key'].endswith('?bandwidthtest=true'));self.assertEqual(w.data['streamServiceSettings']['other'],'preserved');self.assertNotIn('sample',str(r));self.assertTrue(r['prepared']);self.assertFalse(any(m.startswith('Start') for m in w.calls));s.prepare();self.assertEqual(w.data['streamServiceSettings']['key'].count('bandwidthtest=true'),1)
    def test_refuses_non_twitch_or_missing_key_and_all_active_outputs(self):
        for change in ({'key':''},{'service':'Other'},{'server':'rtmp://evil.test/app'},{'key':'placeholder'}):
            w=Wire();w.data['streamServiceSettings'].update(change)
            with self.assertRaises(Refused):StreamTest(w).prepare()
            self.assertNotIn('SetStreamServiceSettings',w.calls)
        w=Wire();w.active=True
        with self.assertRaises(Refused):StreamTest(w).prepare()
        self.assertNotIn('SetStreamServiceSettings',w.calls)
    def test_custom_twitch_ingest_supported_but_does_not_return_credentials(self):
        w=Wire();w.data['streamServiceType']='rtmp_custom';w.data['streamServiceSettings'].pop('service');r=StreamTest(w).prepare();self.assertTrue(r['prepared']);self.assertNotIn('key',r)
    def test_readback_mismatch_is_refused(self):
        w=Wire();old=w.request
        def request(method,data=None):
            if method=='SetStreamServiceSettings':w.calls.append(method);return {}
            return old(method,data)
        w.request=request
        with self.assertRaises(Refused):StreamTest(w).prepare()
