import tempfile,unittest
from pathlib import Path
from PIL import Image
from live_obs import lower_third_image

class PreviewGraphicTests(unittest.TestCase):
    def test_short_title_is_content_width_and_slim_with_transparent_rest_of_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            p=lower_third_image(Path(folder),'Twitch chat ready');im=Image.open(p);box=im.getbbox()
            self.assertLessEqual(box[3]-box[1],100);self.assertLess(box[2]-box[0],960);self.assertGreater(box[1],850);self.assertEqual(im.getpixel((1000,500))[3],0)
    def test_long_title_stays_inside_safe_frame_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            im=Image.open(lower_third_image(Path(folder),'W'*180));box=im.getbbox();self.assertGreaterEqual(box[0],40);self.assertLessEqual(box[2],1880);self.assertLessEqual(box[3]-box[1],100)
