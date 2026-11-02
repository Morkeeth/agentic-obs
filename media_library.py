"""Explicit, copied asset index. No scanning or arbitrary filesystem access at runtime."""
import hashlib,json,re
from pathlib import Path
from streamer import Refused

class AssetLibrary:
    def __init__(self,index,local_index=None):
        self.assets={};self.paths={};self.thumbnails={}
        for file in (index,local_index):
            if file is None or not Path(file).exists():continue
            path=Path(file).resolve();root=path.parent;data=json.loads(path.read_text())
            if data.get('version')!=1 or not isinstance(data.get('assets'),list):raise Refused('Library index version unavailable')
            for row in data['assets']:
                ident=row.get('id','')
                if not re.fullmatch(r'[a-z0-9-]{1,60}',ident) or ident in self.assets:raise Refused('Invalid or duplicate library asset')
                if row.get('private') or re.search(r'\bBAD\b',row.get('provenance',''),re.I):raise Refused('Private or rejected asset refused')
                if row.get('type') not in ('camera','clip','animation','music','lut','border','overlay'):raise Refused('Unknown library asset type')
                if not row.get('licence') or not row.get('provenance') or not isinstance(row.get('tags'),list):raise Refused('Asset provenance and tags required')
                def resource(name):
                    if not isinstance(name,str):raise Refused('Invalid library path')
                    p=root/name
                    if not isinstance(name,str) or p.is_symlink() or p.resolve().parent!=root or not p.is_file():raise Refused('Library path must be a copied file in its own folder')
                    return p.resolve()
                media=resource(row['file'])
                if hashlib.sha256(media.read_bytes()).hexdigest()!=row['sha256']:raise Refused('Library asset hash differs')
                if re.search(r'IMG_(?:3299|330[0-4])',row.get('source_path',''),re.I) or '--private' in row.get('source_path',''):raise Refused('Excluded footage refused')
                self.assets[ident]=dict(row);self.paths[ident]=media
                if row.get('thumbnail'):self.thumbnails[ident]=resource(row['thumbnail'])
    def path(self,ident,thumbnail=False):
        p=(self.thumbnails if thumbnail else self.paths).get(ident)
        if p is None:raise Refused('Select an indexed library asset')
        return p
    def catalog(self):
        return [{k:v for k,v in row.items() if k in ('id','type','title','tags','licence','provenance','redistributable','duration')}|{'thumbnail':'/library/'+ident+'/thumbnail' if ident in self.thumbnails else None,'url':'/library/'+ident} for ident,row in self.assets.items()]
    def find(self,query,kind=None):
        query=query.strip().lower()
        choices=[r for r in self.assets.values() if kind is None or r['type']==kind]
        for row in choices:
            if query in (row['id'],row['title'].lower(),*(str(t).lower() for t in row['tags'])):return dict(row)
        raise Refused('No matching item in the approved library')
