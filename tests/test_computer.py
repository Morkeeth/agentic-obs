import unittest
from computer import BrowserDirector
from streamer import Refused

class Window:
    def __init__(self):self.calls=[];self.url='about:blank';self.y=0
    def show(self,asset):self.url=asset['url'];self.y=0;self.calls.append(('navigate',self.url))
    def scroll(self,n):self.y=max(0,self.y+n);self.calls.append(('scroll',n))
    def describe(self):return {'url':self.url,'title':'Public page','scroll_y':self.y}

class ComputerTests(unittest.TestCase):
    def test_named_project_pages_use_dedicated_browser_and_return_actual_location(self):
        w=Window();b=BrowserDirector(lambda:w)
        r=b.execute('open our GitHub repo');self.assertEqual(r['url'],'https://github.com/Morkeeth/agentic-obs')
        r=b.execute('show the PayPal demo page');self.assertEqual(r['url'],'https://github.com/Morkeeth/approveaccept');self.assertIn('README',r['answer'])
        r=b.execute('find the TwitchCon logo');self.assertIn('bing.com/images/search',r['url']);self.assertIn('TwitchCon',r['url'])
        r=b.execute('scroll down');self.assertEqual(r['scroll_y'],600)
    def test_credentials_local_files_private_urls_and_computer_writes_are_refused(self):
        w=Window();b=BrowserDirector(lambda:w)
        for text in ('open file:///private','open http://127.0.0.1:8808','open https://user:pass@93.184.215.14/','delete my files','post to Twitch','sign into my account'):
            with self.assertRaises(Refused):b.execute(text)
        self.assertEqual(w.calls,[])
    def test_redirect_to_private_address_is_not_accepted_for_staging(self):
        w=Window();w.describe=lambda:{'url':'http://127.0.0.1/private','title':'Private','scroll_y':0}
        with self.assertRaises(Refused):BrowserDirector(lambda:w).execute('open our GitHub repo')

class ShowBrowserTests(unittest.TestCase):
    def test_operator_browser_result_stages_in_live_preview_and_chat_cannot_navigate(self):
        from streamer import Show
        from test_director import Native as OldNative
        from test_live import Native
        from live import LiveStudio
        s=Show(OldNative());s.live=LiveStudio(Native(),['slide']);w=Window();s.browser=BrowserDirector(lambda:w);s.enable()
        r=s.operator_direction('open our GitHub repo','voice');self.assertTrue(r['staged']);self.assertEqual(s.live.current['browser']['url'],'https://github.com/Morkeeth/agentic-obs')
        with self.assertRaises(Refused):s.operator_direction('open our GitHub repo','chat')
        self.assertEqual(len(w.calls),1)
