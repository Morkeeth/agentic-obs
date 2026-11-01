"""Session-local operator-approved public HTTPS page identities; no fetches."""
import hashlib
import re
from urllib.parse import urlsplit, unquote


def public_url(value):
    if not isinstance(value,str) or len(value)>1500 or any(ord(c)<=32 or ord(c)>=127 for c in value):
        raise ValueError('Use a public HTTPS page URL without credentials or secrets')
    try:
        parsed=urlsplit(value)
        if (parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or '?' in value or '#' in value or parsed.port not in (None,443)
            or not re.fullmatch(r'[a-zA-Z0-9.-]+',parsed.hostname) or '.' not in parsed.hostname
            or any(not part or not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?',part) for part in parsed.hostname.split('.'))
            or re.search(r'%(?![0-9A-Fa-f]{2})',value) or '\\' in value or '\\' in unquote(parsed.path) or any(ord(c)<32 or ord(c)==127 for c in unquote(parsed.path))):
            raise ValueError()
    except ValueError:raise ValueError('HTTPS public URLs only; no userinfo, query, fragment or nonstandard port') from None
    return value


class PageCatalog:
    def __init__(self):self.entries={};self.selected=None;self.serial=0
    def register(self,id,name,url):
        if not isinstance(id,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}',id):raise ValueError('Use a short page ID')
        if not isinstance(name,str) or not name.strip() or len(name)>80 or any(ord(c)<32 for c in name):raise ValueError('Use a short page display name')
        if id not in self.entries and len(self.entries)>=10:raise ValueError('Page catalog is full')
        url=public_url(url);self.serial+=1
        revision=hashlib.sha256(f'{self.serial}:{name}:{url}'.encode()).hexdigest()
        self.entries[id]={'id':id,'name':name,'url':url,'revision':revision}
        if self.selected and self.selected['id']==id:self.selected=None
    def select(self,id):
        if id is None:self.selected=None;return
        if not isinstance(id,str) or id not in self.entries:raise ValueError('Choose a registered page')
        item=self.entries[id];self.selected={'id':id,'revision':item['revision']}
    def remove(self,id):
        if not isinstance(id,str) or id not in self.entries:raise ValueError('Choose a registered page')
        del self.entries[id]
        if self.selected and self.selected['id']==id:self.selected=None
    def resolve(self,selection):
        if not isinstance(selection,dict) or set(selection)!={'id','revision'} or not all(isinstance(v,str) for v in selection.values()):raise ValueError('Approved page ID/revision required')
        item=self.entries.get(selection['id'])
        if item is None or item['revision']!=selection['revision']:raise ValueError('Page catalog revision changed')
        return item['url']
    def catalog(self,urls=False):return [{k:v for k,v in item.items() if urls or k!='url'} for item in self.entries.values()]
