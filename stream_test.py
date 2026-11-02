"""Prepare an existing Twitch destination for operator-started ingest testing."""
from copy import deepcopy
from urllib.parse import urlsplit,parse_qsl,urlencode
from streamer import Refused

class StreamTest:
    def __init__(self,wire):self.wire=wire
    def outputs_off(self):
        for method in ('GetStreamStatus','GetRecordStatus','GetVirtualCamStatus'):
            if self.wire.request(method)['outputActive']:raise Refused('Stop all OBS outputs before preparing bandwidth-test mode')
    def prepare(self):
        self.outputs_off()
        original=self.wire.request('GetStreamServiceSettings');settings=original.get('streamServiceSettings',{});kind=original.get('streamServiceType');server=settings.get('server','');parts=urlsplit(server);host=parts.hostname or ''
        twitch_host=(host=='live.twitch.tv' or host.endswith('.contribute.live-video.net') or host.endswith('.twitch.tv')) and parts.scheme in ('rtmp','rtmps') and not parts.username and not parts.password
        common=kind=='rtmp_common' and settings.get('service')=='Twitch' and (server=='auto' or twitch_host)
        custom=kind=='rtmp_custom' and twitch_host
        key=settings.get('key','')
        if not (common or custom) or not isinstance(key,str) or not key.startswith('live_') or len(key.split('?',1)[0])<30:
            raise Refused('Select your existing Twitch OBS service and enter your stream key in OBS first. Credentials are never returned by this app.')
        base,_,query=key.partition('?');params=dict(parse_qsl(query,keep_blank_values=True))
        if set(params)-{'bandwidthtest'}:raise Refused('Unexpected stream-key options; inspect the Twitch service in OBS')
        params['bandwidthtest']='true';target=deepcopy(original);target['streamServiceSettings']['key']=base+'?'+urlencode(params)
        # Use the explicit documented key suffix once, preserving unrelated service fields.
        if 'bwtest' in target['streamServiceSettings']:target['streamServiceSettings']['bwtest']=False
        self.outputs_off()
        self.wire.request('SetStreamServiceSettings',target)
        confirmed=self.wire.request('GetStreamServiceSettings')
        if confirmed.get('streamServiceType')!=kind or confirmed.get('streamServiceSettings',{}).get('key')!=target['streamServiceSettings']['key']:raise Refused('Bandwidth-test preparation was not confirmed; inspect OBS before starting any stream')
        self.outputs_off()
        return {'prepared':True,'outputs_started':False,'message':'Twitch bandwidth-test mode prepared and read back. Live viewing is disabled. Only you can click Start Streaming in OBS; this app never starts it.'}
