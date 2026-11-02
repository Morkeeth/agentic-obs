"""Bounded public browsing in a dedicated empty-profile Chrome."""
from urllib.parse import quote
from visuals import validate_page_url
from streamer import Refused

class BrowserDirector:
    def __init__(self,launch):self.launch=launch;self.window=None;self.current=None
    @staticmethod
    def recognizes(text):
        t=text.strip().rstrip('.!?').lower()
        return t in ('open our github repo','open the github repo','show the paypal demo page','open the paypal demo page','find the twitchcon logo','scroll down','scroll up') or t.startswith(('open https://','open http://','open file://','search for '))
    def state(self):return dict(self.current) if self.current else None
    def execute(self,text):
        cue=text.strip().rstrip('.!?');key=cue.lower();url=None;answer=None
        if key in ('open our github repo','open the github repo'):url='https://github.com/Morkeeth/agentic-obs';answer='Opened our public GitHub repository.'
        elif key in ('show the paypal demo page','open the paypal demo page'):url='https://github.com/Morkeeth/approveaccept';answer='Opened the public PayPal project README. There is no hosted demo.'
        elif key=='find the twitchcon logo':url='https://www.bing.com/images/search?q=TwitchCon+logo+official';answer='Opened a public image search for the official TwitchCon logo.'
        elif key.startswith('search for '):
            query=cue[11:].strip()
            if not 1<=len(query)<=200:raise Refused('Keep public searches under 200 characters')
            url='https://www.bing.com/search?q='+quote(query);answer='Public search results opened in the dedicated browser.'
        elif key.startswith('open '):url=cue[5:];answer='Opened the selected public page.'
        elif key not in ('scroll down','scroll up'):raise Refused('Only public browsing and bounded scrolling are available')
        if url:
            validate_page_url(url)
            if self.window is None:self.window=self.launch()
            self.window.show({'kind':'page','url':url})
        else:
            if self.window is None:raise Refused('Open a public page before scrolling')
            self.window.scroll(600 if key=='scroll down' else -600);answer='Scrolled the dedicated browser.'
        actual=self.window.describe();validate_page_url(actual['url'])
        self.current=dict(actual,answer=answer);return self.state()
