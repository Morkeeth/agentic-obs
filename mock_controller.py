"""Owned experiment controller; deliberately does not inherit model credentials."""
import os
for key in list(os.environ):
    if key.startswith(('OPENAI_', 'STREAM_OPENAI_')):os.environ.pop(key)
os.environ['STREAM_CODEX_ENABLED']='0'
os.environ['AGENTIC_OBS_PORT']='8881'
import stream_agent
stream_agent.PORT=8881
stream_agent.BUILD_TAG='OFFLINE-eventsub-experiment-28oct'
def rules_only(name, model=None):
    if name != 'rules':raise stream_agent.Rejected('offline experiment permits rules only')
    stream_agent.AGENT.planner='rules'
stream_agent.AGENT.set_planner=rules_only
stream_agent.main()
