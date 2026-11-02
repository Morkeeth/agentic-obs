import unittest
from browser_window import BrowserWindow
from streamer import Refused

class Wire:
    def __init__(self):self.calls=[]
    def request(self,method,params):self.calls.append((method,params));return {}

class BrowserWindowTests(unittest.TestCase):
    def test_only_selected_public_page_can_navigate(self):
        wire=Wire();window=BrowserWindow(wire)
        window.show({'kind':'page','url':'https://example.org/','id':'chosen'})
        self.assertEqual(wire.calls,[('Page.navigate',{'url':'https://example.org/'})])
        for asset in ({'kind':'image','url':'https://example.org/'},{'kind':'page','url':'file:///private'},{'kind':'page','url':'http://127.0.0.1/'},{'kind':'page','url':'https://user:pass@93.184.215.14/'}):
            with self.assertRaises(Refused):window.show(asset)
        self.assertEqual(len(wire.calls),1)
    def test_scroll_is_bounded_and_does_not_accept_script(self):
        wire=Wire();window=BrowserWindow(wire)
        for value in ('alert(1)',True,90000,float('nan')):
            with self.assertRaises(Refused):window.scroll(value)
        self.assertEqual(wire.calls,[])
        window.scroll(600)
        self.assertEqual(wire.calls[0][0],'Input.synthesizeScrollGesture')
        self.assertEqual(wire.calls[0][1]['yDistance'],-600)

    def test_navigation_readback_retries_real_chrome_transient_detachment(self):
        class NavigatingWire:
            def __init__(self):self.reads=0
            def request(self,method,params):
                if method=='Page.getNavigationHistory':
                    self.reads+=1
                    if self.reads==1:raise Refused('Dedicated browser page is navigating')
                    return {'currentIndex':0,'entries':[{'url':'https://example.org/','title':'Example Domain'}]}
                return {'cssLayoutViewport':{'pageY':0}}
        wire=NavigatingWire();self.assertEqual(BrowserWindow(wire).describe()['title'],'Example Domain');self.assertEqual(wire.reads,2)
