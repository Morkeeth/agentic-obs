"""Synthetic local fixtures; Twitch EventSub field names, never real account data."""
from datetime import datetime, timezone
def packet(kind='session_welcome', ident='m1', event=None):
    p={'metadata':{'message_id':ident,'message_type':kind,'message_timestamp':datetime.now(timezone.utc).isoformat()},'payload':{}}
    if kind=='session_welcome': p['payload']['session']={'id':'session1','status':'connected','connected_at':datetime.now(timezone.utc).isoformat(),'keepalive_timeout_seconds':10,'reconnect_url':None}
    if event is not None:
        p['metadata'].update(subscription_type='channel.chat.message',subscription_version='1')
        p['payload']={'subscription':{'id':'mock-subscription','status':'enabled','cost':0,'created_at':datetime.now(timezone.utc).isoformat(),'transport':{'method':'websocket','session_id':'session1'},'type':'channel.chat.message','version':'1','condition':{'broadcaster_user_id':'42'}},'event':{'broadcaster_user_id':'42','message_id':ident,'chatter_user_id':'7','broadcaster_user_login':'mock_broadcaster','broadcaster_user_name':'Mock broadcaster','chatter_user_login':'mock_viewer','chatter_user_name':'Mock viewer','color':'#0088FF','badges':[],'message_type':'text','cheer':None,'reply':None,'channel_points_custom_reward_id':None,'source_broadcaster_user_id':None,'source_broadcaster_user_name':None,'source_broadcaster_user_login':None,'source_message_id':None,'source_badges':None,'is_source_only':False,'message':{'text':event,'fragments':[{'type':'text','text':event,'cheermote':None,'emote':None,'mention':None}]}}}
    return p
