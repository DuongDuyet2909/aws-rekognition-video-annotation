import tempfile
import unittest
from pathlib import Path
import zipfile

from scripts.restore_demo import checksum, safe_extract, verify_checksum


class RestoreTests(unittest.TestCase):
    def test_archive_restores_video_and_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root/'demo.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('zebras.mp4', b'test-video')
                bundle.writestr('output/annotations/frame_0000.txt', '0 .5 .5 .2 .2\n')
            verify_checksum(archive, checksum(archive))
            safe_extract(archive, root/'project')
            self.assertEqual((root/'project/zebras.mp4').read_bytes(), b'test-video')
            self.assertTrue((root/'project/output/annotations/frame_0000.txt').is_file())

    def test_path_traversal_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root/'bad.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('zebras.mp4', b'test-video')
                bundle.writestr('output/../../escape.txt', 'invalid')
            with self.assertRaises(ValueError):
                safe_extract(archive, root/'project')
            self.assertFalse((root/'project/zebras.mp4').exists())

    def test_existing_outputs_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'output').mkdir()
            with self.assertRaises(ValueError):
                safe_extract(root/'unused.zip', root)

    def test_bad_checksum_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)/'demo.zip'
            archive.write_bytes(b'not the expected file')
            with self.assertRaises(ValueError):
                verify_checksum(archive, '0'*64)
