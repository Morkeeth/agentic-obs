"""Real HTTP regression for the prior dropped ExceptionGroup response."""
import json,threading,urllib.request,urllib.error
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path
import live_server as s
server=ThreadingHTTPServer(('127.0.0.1',0),s.Handler);s.PORT=server.server_port
threading.Thread(target=server.serve_forever,daemon=True).start()
req=urllib.request.Request(f'http://127.0.0.1:{s.PORT}/api/audio',data=b'audio',headers={'X-Event-Id':'transport-failure-proof'})
with patch('voice_pipeline.process_audio',side_effect=ExceptionGroup('SDK failure',[RuntimeError('private trace must not escape')])):
 try:urllib.request.urlopen(req);raise AssertionError('expected failure')
 except urllib.error.HTTPError as e:
  assert e.code==502;body=json.load(e);assert body['code']=='transport_failure';assert 'private' not in json.dumps(body)
with urllib.request.urlopen(f'http://127.0.0.1:{s.PORT}/api/state') as r:assert r.status==200
server.shutdown()
Path('obs-regression-proof/HTTP-TRANSPORT-FAILURE.json').write_text(json.dumps({'injected_failure':'MCP-style ExceptionGroup','http':502,'body':body,'following_state_http':200},indent=2))
print('PASS: bounded502 and following request200')
