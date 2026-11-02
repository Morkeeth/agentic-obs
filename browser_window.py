"""Dedicated, empty-profile Chrome control for the native window-capture fallback."""
import json
import math
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
import websocket
from streamer import Refused
from visuals import validate_page_url

class CdpWire:
    ALLOWED={'Page.navigate','Input.synthesizeScrollGesture','Page.getLayoutMetrics','Page.getNavigationHistory','Emulation.setDeviceMetricsOverride'}
    def __init__(self,url):
        parsed=urlsplit(url)
        if parsed.scheme!='ws' or parsed.hostname!='127.0.0.1' or not parsed.path.startswith('/devtools/page/'):
            raise Refused('Only the dedicated local Chrome page is supported')
        self.ws=websocket.create_connection(url,timeout=8,suppress_origin=True)
        self.lock=threading.Lock();self.sequence=0
    def request(self,method,params):
        if method not in self.ALLOWED:raise Refused('Browser action is not allowed')
        with self.lock:
            self.sequence+=1;ident=self.sequence
            self.ws.send(json.dumps({'id':ident,'method':method,'params':params}))
            while True:
                reply=json.loads(self.ws.recv())
                if reply.get('id')!=ident:continue
                if 'error' in reply:
                    if reply['error'].get('message')=='Not attached to an active page':
                        raise Refused('Dedicated browser page is navigating')
                    raise Refused('Dedicated browser action failed')
                result=reply.get('result',{})
                if result.get('errorText'):raise Refused('Selected page navigation failed')
                return result
    def close(self):self.ws.close()

class BrowserWindow:
    def __init__(self,wire):self.wire=wire
    def show(self,asset):
        if asset.get('kind')!='page':raise Refused('Choose a selected public page')
        validate_page_url(asset.get('url'))
        return self.wire.request('Page.navigate',{'url':asset['url']})
    def scroll(self,distance):
        if isinstance(distance,bool) or not isinstance(distance,(int,float)) or not math.isfinite(distance) or not -1200<=distance<=1200:
            raise Refused('Scroll must be between -1200 and 1200 pixels')
        return self.wire.request('Input.synthesizeScrollGesture',{'x':400,'y':350,'yDistance':-distance,'speed':700,'gestureSourceType':'mouse'})
    def describe(self):
        for attempt in range(40):
            try:return self._describe()
            except Refused as exc:
                if str(exc)!='Dedicated browser page is navigating' or attempt==39:raise
                time.sleep(.1)
    def _describe(self):
        history=self.wire.request('Page.getNavigationHistory',{});entry=history['entries'][history['currentIndex']];metrics=self.wire.request('Page.getLayoutMetrics',{})
        return {'url':entry['url'],'title':entry.get('title',''),'scroll_y':metrics.get('cssLayoutViewport',metrics.get('layoutViewport',{})).get('pageY',0)}
    def close(self):
        self.wire.close()
        if getattr(self,'process',None) and self.process.poll() is None:
            self.process.terminate();self.process.wait(timeout=10)
    @classmethod
    def launch(cls,folder,port=9223,headless=False):
        if port not in (0,9223):raise Refused('Dedicated Chrome uses a new local endpoint')
        folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        # Never attach to a pre-existing debugging endpoint or a personal profile.
        try:
            if port==0:raise OSError('New endpoint requested')
            urllib.request.urlopen('http://127.0.0.1:9223/json/version',timeout=.3)
        except OSError:pass
        else:raise Refused('Dedicated Chrome port is already in use')
        executable='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        args=[executable]+(['--headless=new'] if headless else [])+['--user-data-dir='+str(folder),'--remote-debugging-port='+str(port),
            '--remote-debugging-address=127.0.0.1','--no-first-run','--no-default-browser-check','--disable-sync',
            '--window-size=1920,1080','--new-window','about:blank']
        process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(50):
            if process.poll() is not None:raise Refused('Dedicated Chrome did not start')
            try:
                actual_port=int((folder/'DevToolsActivePort').read_text().splitlines()[0]) if port==0 else port
                targets=json.load(urllib.request.urlopen(f'http://127.0.0.1:{actual_port}/json/list',timeout=.3))
                pages=[t for t in targets if t.get('type')=='page' and t.get('url')=='about:blank']
                if len(pages)==1:
                    window=cls(CdpWire(pages[0]['webSocketDebuggerUrl']));window.process=process
                    window.wire.request('Emulation.setDeviceMetricsOverride',{'width':1920,'height':1080,'deviceScaleFactor':1,'mobile':False});return window
            except OSError:pass
            time.sleep(.1)
        raise Refused('Dedicated Chrome page unavailable')
