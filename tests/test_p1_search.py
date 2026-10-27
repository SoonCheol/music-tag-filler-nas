"""P1 regression: generated audio, mocked external services, no library mounts."""
import io
import json
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch
from PIL import Image
import test_p0_storage as p0
from app import main, storage, search_service as service
from app.upstream import match, net, search_itunes as itunes, search_mb as mb, search_acoustid as acoustic, search_lyrics as lyrics


class P1Tests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp = p0.P0Tests.setUp
    tearDown = p0.P0Tests.tearDown
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job
    item = p0.P0Tests.item
    request = p0.P0Tests.request
    http = p0.P0Tests.http

    def candidate(self, **extra):
        return match.Candidate(title="Wonderful Song", artist="Singer", album="Album", length=180,
                               sources=extra.pop("sources", ["iTunes"]), **extra)

    def test_country_fallback_and_album_cover(self):
        row = {"trackName": "Wonderful Song", "artistName": "Singer", "trackTimeMillis": 180000}
        with patch.object(net, "get_json", side_effect=[{"results": []}, {"results": [row]}]) as call:
            self.assertEqual(itunes.search("Singer Wonderful Song", "JP")[0].length, 180)
            self.assertEqual([c.args[1]["country"] for c in call.call_args_list], ["JP", "US"])
        with patch.object(net, "get_json", return_value={"results": [{"collectionName": "Album", "artistName": "Singer", "artworkUrl100": "https://example/100x100bb.jpg"}]}) as call:
            self.assertIn("1000x1000bb", itunes.album_artwork("Album", "Singer", "KR"))
            self.assertEqual(call.call_args.args[1]["country"], "US")

    def test_musicbrainz_query_fallback(self):
        with patch.object(net, "get_json", side_effect=[{"recordings": []}, {"recordings": [{"id": "recording", "title": "Wonderful Song", "artist-credit": [{"name": "Singer"}]}]}]) as call:
            result = mb.search("Wonderful Song", "Singer", "Singer Wonderful Song")
            self.assertEqual(result[0].mb_recording_id, "recording")
            self.assertEqual(call.call_count, 2)
            self.assertIn("recording:", call.call_args_list[0].args[1]["query"])

    def test_merge_deduplicate_and_auto_guard(self):
        one = self.candidate()
        two = self.candidate(sources=["MusicBrainz"], mb_recording_id="recording")
        ranked = service.rank([one, one, two], one.title, one.artist, 180)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(set(ranked[0]["sources"]), {"iTunes", "MusicBrainz"})
        self.assertIsNotNone(service.auto_pick(ranked, one.title, one.artist, 180))
        self.assertIsNone(service.auto_pick(ranked, "track01", "", 180))
        self.assertIsNone(service.auto_pick(ranked, one.title + " (Live)", one.artist, 180))
        self.assertIsNone(service.auto_pick(ranked, one.title, one.artist, 240))

    def test_missing_key_and_capabilities_no_secret(self):
        with patch.dict("os.environ", {"ACOUSTID_API_KEY": "", "SEARCH_COUNTRY": ""}), patch.object(service.pipeline, "search_sound") as call:
            result, errors = service.sound(self.root / "none", service.configuration(self.data), "query", 180)
            self.assertFalse(result)
            self.assertIn("missing_api_key", [e["code"] for e in errors])
            call.assert_not_called()
        (self.data / "acoustid_key.txt").write_text("fixture-secret-not-sent")
        caps = service.capabilities(self.data)
        self.assertTrue(caps["acoustid_key_configured"])
        self.assertNotIn("fixture-secret", json.dumps(caps))

    def test_real_fingerprint_without_file_changes(self):
        path = self.root / "fingerprint.flac"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=15", str(path)], check=True)
        before = storage.revision(path)
        duration, fingerprint = acoustic.fingerprint(str(path))
        self.assertGreater(duration, 10)
        self.assertTrue(fingerprint)
        self.assertEqual(storage.revision(path), before)

    def test_acoustid_only_fingerprint_payload_and_bad_key(self):
        response = Mock()
        response.json.return_value = {"status": "ok", "results": []}
        with patch.object(net, "request", return_value=response) as call:
            self.assertEqual(acoustic.lookup("numeric-fingerprint", 180, "test-fixture-key"), [])
            self.assertEqual(set(call.call_args.kwargs["data"]), {"client", "duration", "fingerprint", "meta", "format"})
        response.json.return_value = {"status": "error", "error": {"code": 4, "message": "invalid API key"}}
        with patch.object(net, "request", return_value=response), self.assertRaises(acoustic.NoApiKey):
            acoustic.lookup("fingerprint", 180, "test-fixture-key")

    def test_text_empty_fingerprint_fallback_and_partial_errors(self):
        with patch.object(itunes, "search", return_value=[]), patch.object(mb, "search", return_value=[]), patch.object(service, "sound", return_value=([self.candidate()], [])) as call:
            found = service.search(self.root / "x", "Singer - Wonderful Song", "US", 180, self.data, use_fingerprint=True)
            self.assertTrue(found["used_fingerprint"])
            self.assertEqual(found["search_status"], "matched")
            self.assertEqual(call.call_count, 1)
        with patch.object(itunes, "search", return_value=[self.candidate()]), patch.object(mb, "search", side_effect=net.RateLimited(7)), patch.object(service, "sound") as call:
            found = service.search(self.root / "x", "Singer - Wonderful Song", "US", 180, self.data)
            self.assertEqual(found["search_status"], "partial")
            self.assertEqual(found["search_errors"][0]["code"], "rate_limited")
            call.assert_not_called()

    def test_not_found_network_invalid_and_cancelled(self):
        for failure, code in [(net.NetworkError("timeout"), "network_error"), (net.NetworkError("bad json"), "invalid_response"), (net.NetworkError("HTTP 500"), "api_error")]:
            self.assertEqual(service.network_error("test", failure)["code"], code)
        with patch.object(itunes, "search", return_value=[]), patch.object(mb, "search", return_value=[]):
            self.assertEqual(service.search(self.root / "x", "query", "US", 180, self.data, use_fingerprint=False)["search_status"], "not_found")
        cancel = threading.Event()
        cancel.set()
        with patch.object(itunes, "search") as call:
            self.assertEqual(service.search(self.root / "x", "query", "US", 180, self.data, cancel=cancel)["search_status"], "cancelled")
            call.assert_not_called()

    def test_cover_validation_conversion_fallback_cache(self):
        buffer = io.BytesIO()
        Image.new("RGBA", (1600, 800), "blue").save(buffer, "PNG")
        image = service.prepare_image(buffer.getvalue())
        with Image.open(io.BytesIO(image)) as opened:
            self.assertEqual((opened.format, opened.size), ("JPEG", (1000, 500)))
        with self.assertRaises(Exception):
            service.prepare_image(b"not-an-image")
        value = service.candidate_dict(self.candidate(mb_release_group_id="group", cover_url="https://bad"))
        service._cover_cache.clear()
        with patch.object(net, "get_bytes", side_effect=[b"broken", buffer.getvalue()]) as call:
            self.assertTrue(service.fetch_cover(value)[0])
            self.assertTrue(service.fetch_cover(value)[0])
            self.assertEqual(call.call_count, 2)
            self.assertIn("release-group/group", call.call_args.args[0])

    def test_lrclib_validation_and_busy(self):
        row = {"id": 1, "trackName": "Wonderful Song", "artistName": "Singer", "duration": 180,
               "plainLyrics": "These are the original words of a wonderful song"}
        self.assertEqual(lyrics.pick([row], "Wonderful Song", "Singer", 180)[0], lyrics.FOUND)
        for change in [{"artistName": "Other"}, {"duration": 190}, {"trackName": "Wonderful Song (Instrumental)"}, {"syncedLyrics": "[04:00.00]Too late"}]:
            self.assertNotEqual(lyrics.pick([{**row, **change}], "Wonderful Song", "Singer", 180)[0], lyrics.FOUND)
        with patch.object(lyrics, "_search", side_effect=[[row], net.NetworkError("timeout")]):
            self.assertEqual(lyrics.find("Wonderful Song", "Singer", 180).status, lyrics.BUSY)
        self.assertTrue(lyrics.marker_only("(Instrumental)"))
        with patch.object(lyrics, "_search") as call:
            self.assertEqual(lyrics.find("Song (Instrumental)", "Singer", 180).status, lyrics.INSTRUMENTAL)
            call.assert_not_called()

    def test_lrclib_parenthetical_localized_title_alias(self):
        row = {"id": 10986136, "trackName": "Because of you (너 때문에)", "artistName": "After School",
               "duration": 241, "plainLyrics": "Synthetic fixture lyric text for validation only"}
        self.assertEqual(lyrics._title_ok("Because of you (너 때문에)", "너 때문에"), True)
        self.assertEqual(lyrics._title_ok("Because of you (2011 New Recording)", "너 때문에"), False)
        with patch.object(lyrics, "_search", side_effect=[[row], []]) as lookup:
            found = lyrics.find("너 때문에", "After School", 241)
        self.assertEqual((found.status, found.record_id), (lyrics.FOUND, 10986136))
        self.assertEqual(lookup.call_args_list[0].args[0], {"track_name": "너 때문에", "artist_name": "After School"})
        self.assertEqual(lookup.call_args_list[1].args[0], {"q": "AfterSchool 너 때문에"})

    def test_lrclib_api_error_is_distinct_from_empty_results(self):
        with patch.object(lyrics, "_search", side_effect=[net.NetworkError("HTTP 502")]):
            failed = lyrics.find("Song", "Singer", 180)
        with patch.object(lyrics, "_search", side_effect=[[], []]):
            empty = lyrics.find("Song", "Singer", 180)
        self.assertEqual(failed.status, lyrics.BUSY)
        self.assertIn("API 오류 (HTTP 502)", failed.message)
        self.assertEqual((empty.status, empty.message), (lyrics.NOT_FOUND, ""))

    def test_lrclib_overload_retry(self):
        responses = [Mock(status_code=503, headers={}) for _ in range(3)] + [Mock(status_code=200)]
        with patch.object(net, "session") as session, patch.object(net.throttle, "wait"), patch.object(net.throttle, "slow_down") as slow, patch.object(net, "_sleep") as sleep:
            session.return_value.request.side_effect = responses
            self.assertEqual(net.request("GET", lyrics.API_SEARCH).status_code, 200)
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2, 4])
            slow.assert_not_called()

    def test_lyrics_conflict_and_oversized_lone_text(self):
        row = {"trackName": "Wonderful Song", "artistName": "Singer", "duration": 180}
        first = {**row, "id": 1, "plainLyrics": "Flowers blossom gently underneath the golden summer sunshine"}
        other = {**row, "id": 2, "plainLyrics": "Zigzag quartz rhythms explode beyond mysterious purple galaxies"}
        self.assertEqual(lyrics.pick([first, other], "Wonderful Song", "Singer", 180)[0], lyrics.CONFLICT)
        self.assertNotEqual(lyrics.pick([{**row, "plainLyrics": "words " * 1000}], "Wonderful Song", "Singer", 180)[0], lyrics.FOUND)

    def test_official_release_priority(self):
        releases = [{"id": "bootleg", "status": "Bootleg", "date": "1960", "release-group": {"primary-type": "Album"}},
                    {"id": "compilation", "status": "Official", "date": "1961", "release-group": {"primary-type": "Album", "secondary-types": ["Compilation"]}},
                    {"id": "original", "status": "Official", "date": "1962", "release-group": {"primary-type": "Album"}}]
        self.assertEqual(mb._pick_release(releases)["id"], "original")

    def test_marker_lyrics_fill_and_restore_all_formats(self):
        for ext in ("mp3", "flac", "m4a", "ogg"):
            with self.subTest(ext=ext):
                path = self.copy("marker." + ext)
                p0.tags.write_file(str(path), p0.tags.read_file(str(path)).tags, lyrics="(Instrumental)")
                before = path.read_bytes()
                result = self.job([path])[0]
                with patch.object(lyrics, "find", return_value=lyrics.LyricsResult(lyrics.FOUND, "Replacement words for this generated test song")):
                    response = self.http(self.request([self.item(result)], fill_lyrics=True))
                self.assertEqual(response["saved"], 1)
                self.assertIn("Replacement", p0.tags.read_lyrics(str(path)))
                self.http({"expected_revision": storage.revision(path)}, "/api/revert/" + path.name)
                self.assertEqual(path.read_bytes(), before)

    def test_four_formats_cover_save_and_exact_restore(self):
        for ext in ("mp3", "flac", "m4a", "ogg"):
            with self.subTest(ext=ext):
                path = self.copy("asset." + ext)
                before = path.read_bytes()
                self.assertTrue(p0.tags.read_cover(str(path))[0])
                result = self.job([path])[0]
                candidate = result["candidates"][0]
                item = self.item(result, selection="manual", candidate_id=candidate["id"], include_cover=True)
                with patch.object(service, "fetch_cover", return_value=(p0.image_bytes("blue"), [])):
                    response = self.http(self.request([item]))
                self.assertEqual(response["saved"], 1)
                self.assertNotEqual(p0.tags.read_cover(str(path))[0], self.cover)
                self.http({"expected_revision": storage.revision(path)}, "/api/revert/" + path.name)
                self.assertEqual(path.read_bytes(), before)

    def test_manual_research_apply_and_stale_revision(self):
        path = self.copy()
        result = self.job([path])[0]
        found = {"candidates": [service.candidate_dict(self.candidate())], "search_status": "matched", "search_errors": [],
                 "query_title": "Wonderful Song", "query_artist": "Singer", "query": "Singer - Wonderful Song", "country": "JP"}
        with patch.object(service, "search", return_value=found):
            response = self.http({"path": path.name, "query": "Singer - Wonderful Song", "country": "JP", "expected_revision": storage.revision(path)}, "/api/jobs/test/search")
        updated = response["result"] if "result" in response else response
        candidate = updated["candidates"][0]
        item = self.item(updated, selection="manual", candidate_id=candidate["id"], values={"title": "Wonderful Song"})
        self.assertEqual(self.http(self.request([item]))["saved"], 1)
        self.http({"path": path.name, "query": "query", "expected_revision": "0" * 64}, "/api/jobs/test/search", expected=409)

    def test_cover_concurrent_requests_share_upstream_and_release_keys_differ(self):
        from concurrent.futures import ThreadPoolExecutor
        import time
        service._cover_cache.clear()
        value=service.candidate_dict(self.candidate(cover_url='https://example/shared'))
        other={**value,'title':'Different title'}
        entered,release=threading.Event(),threading.Event()
        def download(*args,**kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return p0.image_bytes('blue')
        with patch.object(net,'get_bytes',side_effect=download) as call:
            with ThreadPoolExecutor(3) as pool:
                a=pool.submit(service.fetch_cover,value)
                self.assertTrue(entered.wait(3))
                b=pool.submit(service.fetch_cover,value)
                c=pool.submit(service.fetch_cover,other)
                try:
                    for _ in range(100):
                        with service._cover_lock:
                            pending=len(service._cover_pending)
                        if pending>=3:break
                        time.sleep(.01)
                    self.assertGreaterEqual(pending,3)
                    self.assertEqual(call.call_count,1)
                finally:release.set()
                self.assertEqual(a.result()[0],b.result()[0]);self.assertEqual(a.result()[0],c.result()[0])
        self.assertEqual(service._cover_pending,{})
        first={**value,'mb_release_id':'release-a','mb_release_group_id':'group-a'}
        second={**value,'mb_release_id':'release-b','mb_release_group_id':'group-b'}
        self.assertNotEqual(service.candidate_id(first),service.candidate_id(second))
        service._cover_cache.clear()
        with patch.object(net,'get_bytes',side_effect=[p0.image_bytes('red'),p0.image_bytes('blue')]) as call:
            self.assertNotEqual(service.fetch_cover(first)[0],service.fetch_cover(second)[0])
            self.assertEqual(call.call_count,2)

    def test_cover_fallback_requires_both_names_and_failure_can_retry(self):
        for album,artist in [('Album','Wrong singer'),('Wrong album','Singer')]:
            with patch.object(net,'get_json',return_value={'results':[{'collectionName':album,'artistName':artist,'artworkUrl100':'https://example/100x100.jpg'}]}):
                self.assertIsNone(itunes.album_artwork('Album','Singer','US'))
        service._cover_cache.clear()
        value=service.candidate_dict(self.candidate(cover_url='https://example/retry'))
        with patch.object(net,'get_bytes',side_effect=[net.NetworkError('timeout'),p0.image_bytes('blue')]) as call,patch.object(itunes,'album_artwork',return_value=None):
            self.assertIsNone(service.fetch_cover(value)[0])
            self.assertIsNotNone(service.fetch_cover(value)[0])
            self.assertEqual(call.call_count,2)
