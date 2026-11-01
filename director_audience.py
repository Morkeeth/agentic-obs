"""Fixed-cue sink for the independently rebuilt Twitch EventSub transport.

Pass DirectorSink() as run(..., send=...). No new OAuth/scopes or viewer prompt
path. Local numeric vote ingress is separate and is not claimed as live Twitch.
"""
import json
import urllib.request

from director import FIXED


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


class DirectorSink:
    def __init__(self, port=8880):
        if type(port) is not int or port in (4455, 8877, 8878, 8879) or not 1024 <= port <= 65535:
            raise ValueError('Choose the expanded director loopback HTTP port')
        self.url = f'http://127.0.0.1:{port}'

    def __call__(self, cue):
        if not isinstance(cue, str) or cue not in FIXED: raise ValueError('Only fixed transport cues are permitted')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        body = json.dumps({'cue': cue}).encode()
        request = urllib.request.Request(self.url+'/api/audience', data=body,
            headers={'Content-Type': 'application/json', 'Origin': self.url})
        with opener.open(request, timeout=2) as response: return json.load(response)
