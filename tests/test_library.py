import hashlib,json,tempfile,unittest
from pathlib import Path
from streamer import Refused
from media_library import AssetLibrary

class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name)
        ((self.folder/'clip.mp4').resolve()).write_bytes(b'owned clip')
        self.row={'id':'notification-burst','type':'animation','title':'Glassy notifications','file':'clip.mp4','licence':'Creator permission','provenance':'KEEP, source clip id','tags':['notification','notification burst'],'sha256':hashlib.sha256(b'owned clip').hexdigest(),'redistributable':True}
    def load(self,row=None):
        (self.folder/'index.json').write_text(json.dumps({'version':1,'assets':[row or self.row]}));return AssetLibrary(self.folder/'index.json')
    def test_named_tags_select_only_indexed_owned_assets(self):
        library=self.load();self.assertEqual(library.find('notification burst','animation')['id'],'notification-burst')
        self.assertEqual(library.path('notification-burst'),(self.folder/'clip.mp4').resolve())
        with self.assertRaises(Refused):library.find('anything else')
    def test_private_bad_traversal_and_hash_mismatch_are_refused(self):
        for changed in ({'private':True},{'provenance':'Latest BAD'},{'file':'../secret.mp4'},{'sha256':'0'*64}):
            with self.subTest(changed=changed):
                with self.assertRaises(Refused):self.load(dict(self.row,**changed))
    def test_public_catalog_never_exposes_absolute_source_paths(self):
        library=self.load();self.assertEqual(library.catalog()[0]['id'],'notification-burst');self.assertNotIn(str(self.folder),json.dumps(library.catalog()))
