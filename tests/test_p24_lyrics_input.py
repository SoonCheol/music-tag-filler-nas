"""Direct lyric input through the real HTTP save API; generated audio only."""
import unittest
from unittest.mock import patch
import test_p0_storage as p0
from app import main, storage


class DirectLyricsTests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp = p0.P0Tests.setUp
    tearDown = p0.P0Tests.tearDown
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job
    item = p0.P0Tests.item
    request = p0.P0Tests.request
    http = p0.P0Tests.http

    def payload(self, row, text, **options):
        item = self.item(row, selection="none", fields=[], values={}, lyrics_text=text)
        return self.request([item], save_lyrics=True, **options)

    def test_direct_lyrics_four_formats_and_exact_restore(self):
        for extension in ("mp3", "flac", "m4a", "ogg"):
            with self.subTest(extension=extension):
                path = self.copy("direct." + extension)
                original = path.read_bytes()
                before = p0.tags.read_file(str(path))
                row = self.job([path])[0]
                text = "직접 입력한 가사\nPasted second line"
                with patch.object(main._lyrics_service, "legacy_lookup", side_effect=AssertionError("Unexpected search")):
                    response = self.http(self.payload(row, text, only_empty=False))
                self.assertEqual(response["saved"], 1, response)
                self.assertEqual(response["failed"], 0, response)
                after = p0.tags.read_file(str(path))
                self.assertEqual(after.lyrics, text)
                self.assertEqual((after.tags, after.cover, after.ids, after.synced),
                                 (before.tags, before.cover, before.ids, before.synced))
                self.assertIn("lyrics", response["results"][0]["saved_assets"])
                restored = storage.restore(path, self.root, self.backups, storage.revision(path))
                self.assertTrue(restored["exact"])
                self.assertEqual(path.read_bytes(), original)

    def test_checkbox_protection_and_empty_input_preserve_bytes(self):
        for index, options in enumerate(({"save_lyrics": False}, {"only_empty": True}, {"text": " \n "})):
            with self.subTest(options=options):
                path = self.copy("protected-%s.mp3" % index)
                row = self.job([path])[0]
                payload = self.payload(row, options.get("text", "Replacement"), only_empty=False)
                payload.update({key: value for key, value in options.items() if key != "text"})
                before = path.read_bytes(), path.stat().st_mtime_ns
                response = self.http(payload)
                self.assertEqual(response["failed"], 0, response)
                self.assertEqual(response["saved"], 0, response)
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_empty_lyrics_can_be_filled_without_search(self):
        path = self.copy("empty.mp3", blank=True)
        row = self.job([path])[0]
        response = self.http(self.payload(row, "New lyrics", only_empty=True))
        self.assertEqual(response["saved"], 1, response)
        after = p0.tags.read_file(str(path))
        self.assertEqual(after.lyrics, "New lyrics")
        self.assertEqual(after.tags.title, "")

    def test_stale_revision_rejected_without_modifying_file(self):
        path = self.copy("stale.mp3")
        row = self.job([path])[0]
        payload = self.payload(row, "Must not save")
        payload["items"][0]["expected_revision"] = "f" * 64
        before = path.read_bytes()
        response = self.http(payload)
        self.assertEqual(response["failed"], 1, response)
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
