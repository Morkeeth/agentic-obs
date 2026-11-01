"""Resolver boundary checks; actual artifact RED/GREEN is run separately with otool."""
from pathlib import Path
import tempfile
import unittest
from director_bundle_closure import Audit, commands, expand


class ClosureBoundaries(unittest.TestCase):
    def test_load_identity_is_not_dependency_and_weak_edges_stay_optional(self):
        text='''image:
Load command 0
          cmd LC_ID_DYLIB
      cmdsize 64
         name @rpath/Example.dylib (offset 24)
Load command 1
          cmd LC_RPATH
      cmdsize 48
         path @loader_path/../Frameworks (offset 12)
Load command 2
          cmd LC_LOAD_DYLIB
      cmdsize 64
         name @rpath/Required.dylib (offset 24)
Load command 3
          cmd LC_LOAD_WEAK_DYLIB
      cmdsize 64
         name @rpath/Optional.dylib (offset 24)
Load command 4
          cmd LC_REEXPORT_DYLIB
      cmdsize 64
         name /usr/lib/libSystem.B.dylib (offset 24)
'''
        paths,loads=commands(text)
        self.assertEqual(paths,['@loader_path/../Frameworks'])
        self.assertEqual(loads,[('@rpath/Required.dylib',False),('@rpath/Optional.dylib',True),('/usr/lib/libSystem.B.dylib',False)])

    def test_loader_rpath_is_anchored_at_declaring_image_not_the_dependency(self):
        image=Path('/owned/Example.app/Contents/PlugIns/Effect.plugin/Contents/MacOS/Effect')
        executable=Path('/owned/Example.app/Contents/MacOS/Example')
        loader=expand('@loader_path/../Frameworks',image,executable)
        root=expand('@executable_path/../Frameworks',image,executable)
        self.assertEqual(loader,Path('/owned/Example.app/Contents/PlugIns/Effect.plugin/Contents/Frameworks'))
        self.assertEqual(root,Path('/owned/Example.app/Contents/Frameworks'))
        audit=Audit.__new__(Audit)
        self.assertEqual(audit.candidates('@rpath/Required.dylib',image,executable,(loader,root)),[loader/'Required.dylib',root/'Required.dylib'])
        self.assertIsNone(expand('Required.dylib',image,executable))

    def test_sdk_and_escaped_symlink_cannot_complete_private_bundle_closure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent,prefix='.director-test-closure-') as value:
            root=Path(value).resolve();bundle=root/'Example.app';bundle.mkdir()
            sdk=root/'cached-sdk';sdk.mkdir();library=sdk/'Required.dylib';library.write_bytes(b'fixture only; never loaded')
            (bundle/'escaped.dylib').symlink_to(library)
            resident=bundle/'Resident.dylib';resident.write_bytes(b'fixture only; never loaded')
            audit=Audit.__new__(Audit);audit.bundle=bundle
            self.assertTrue(audit.resident(resident))
            self.assertFalse(audit.resident(library))
            self.assertFalse(audit.resident(bundle/'escaped.dylib'))


if __name__=='__main__':unittest.main()
