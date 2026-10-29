"""Pure CPU helper controls. Importing the GPU helper does not start it."""
import unittest
import native_preview


class HeaderControls(unittest.TestCase):
    def test_independent_jpeg_sof_geometry(self):
        body=b'\xff\xd8\xff\xc0\x00\x0b\x08\x04\x38\x07\x80\x01\x01\x11\x00\xff\xd9'
        self.assertEqual(native_preview.jpeg_dimensions(body),(1920,1080))
        for bad in [body[:-2],body.replace(b'\x00\x0b',b'\xff\xff'),b'\xff\xd8\xff\xd9']:
            with self.subTest(bad=bad),self.assertRaises(ValueError):native_preview.jpeg_dimensions(bad)

    def test_identity_keeps_same_timestamp_distinct_by_sequence_and_session(self):
        row={'sourceId':'north','sourceSessionId':'session','sequence':'7','sourceTimeNs':'123','modelRevision':'sha'}
        self.assertNotEqual(native_preview.identity(row),native_preview.identity({**row,'sequence':'8'}))
        self.assertNotEqual(native_preview.identity(row),native_preview.identity({**row,'sourceSessionId':'new'}))


if __name__=='__main__':unittest.main()
