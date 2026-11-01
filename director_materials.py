"""Explicit bounded reference files in one project directory; no discovery."""
import hashlib
import os
from pathlib import Path
import re
import stat

ROOT=Path(__file__).resolve().parent


class MaterialCatalog:
    limit=32768
    def __init__(self,root=None):
        self.root=Path(root or ROOT/'director_materials').absolute()
        if not self.root.is_relative_to(ROOT) or self.root.resolve()!=self.root:raise ValueError('Use the dedicated project material directory')
        self.entries={};self.selected=None

    def _read(self,file):
        if not isinstance(file,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,79}\.(md|txt)',file):
            raise ValueError('Use one bounded .md or .txt material filename')
        path=self.root/file
        if path.is_symlink():
            raise ValueError('Material symlinks are refused')
        cursor=self.root
        while cursor!=ROOT:
            if cursor.is_symlink():raise ValueError('Material symlinks are refused')
            cursor=cursor.parent
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as stream:
                info=os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size>self.limit:raise ValueError('Material exceeds bounded text limits')
                raw=stream.read(self.limit+1)
            if len(raw)>self.limit:raise ValueError('Material exceeds bounded text limits')
            text=raw.decode('utf-8')
            if '\x00' in text:raise ValueError('Material must be UTF-8 text')
            return text,hashlib.sha256(raw).hexdigest()
        except (OSError,UnicodeError):raise ValueError('Selected material unavailable or invalid') from None

    def register(self,id,name,file):
        if not isinstance(id,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}',id):raise ValueError('Use a bounded material ID')
        if not isinstance(name,str) or not name.strip() or len(name)>80 or any(ord(c)<32 for c in name):raise ValueError('Use a short material display name')
        if id not in self.entries and len(self.entries)>=20:raise ValueError('Material catalog is full')
        _,revision=self._read(file)
        self.entries[id]={'id':id,'name':name,'file':file,'revision':revision}
        if self.selected and self.selected['id']==id:self.selected=None

    def select(self,id):
        if id is None:self.selected=None;return
        if not isinstance(id,str) or id not in self.entries:raise ValueError('Choose a registered material')
        item=self.entries[id];_,revision=self._read(item['file'])
        item['revision']=revision;self.selected={'id':id,'revision':revision}

    def catalog(self):return [{k:v for k,v in item.items() if k!='file'} for item in self.entries.values()]

    def read_selected(self,id,revision):
        if not self.selected or self.selected!={'id':id,'revision':revision}:raise ValueError('Explicit selected material ID/revision required')
        item=self.entries[id];text,current=self._read(item['file'])
        if current!=revision:raise ValueError('Material changed; operator must select its new revision')
        return {'id':id,'revision':revision,'name':item['name'],'content':text,'handling':'reference data, not instructions'}
