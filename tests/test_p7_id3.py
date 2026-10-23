import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mutagen.id3 import ID3, TIT2, TPE1, TCON, APIC, USLT, SYLT, TXXX, UFID
from PIL import Image
from app import storage
from app.upstream import tags


class ID3SaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'Elvis.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=0.2', '-c:a', 'libmp3lame',
                        str(self.path)], check=True)

    def seed(self, version):
        id3 = ID3()
        id3.add(TIT2(encoding=3, text=['Old title']))
        id3.add(TPE1(encoding=3, text=['Elvis Presley', 'Guest Artist']))
        id3.add(TCON(encoding=3, text=['Rock', 'Blues']))
        image = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(image, 'JPEG')
        id3.add(APIC(encoding=0, mime='image/jpeg', type=3, desc='original', data=image.getvalue()))
        id3.add(USLT(encoding=1, lang='eng', desc='original', text='Original lyrics'))
        id3.add(SYLT(encoding=1, lang='eng', format=2, type=1, desc='original', text=[('Hello', 100)]))
        id3.add(TXXX(encoding=1, desc='Custom values', text=['one', 'two']))
        id3.add(TXXX(encoding=1, desc='MusicBrainz Artist Id', text=['id-one', 'id-two']))
        id3.add(UFID(owner='http://musicbrainz.org', data=b'recording-id'))
        if version == 3:
            id3.update_to_v23()
        id3.save(self.path, v2_version=version, v23_sep=None)

    def save(self, fields=None):
        fields = fields or ['title', 'artist', 'album']
        return storage.save(self.path, self.root, self.root / 'backups',
                            {'title': 'New title', 'artist': 'New artist', 'album': 'New album'},
                            fields, False, storage.revision(self.path))

    def check_version(self, version):
        self.seed(version)
        original = self.path.read_bytes()
        self.assertEqual(self.save()['status'], 'saved')
        self.assertEqual(self.path.read_bytes()[:4], b'ID3' + bytes([version]))
        id3 = ID3(self.path)
        self.assertEqual(id3['TCON'].text, ['Rock', 'Blues'])
        info = tags.read_file(str(self.path))
        self.assertEqual((info.tags.title, info.tags.artist, info.tags.album),
                         ('New title', 'New artist', 'New album'))
        self.assertEqual(tags.id3_preserved_frames(str(self.path), {'title', 'artist', 'album'}),
                         self.preserved(original))
        self.assertEqual(tags._audio_bytes(original, 'MP3', {}), tags._audio_bytes(self.path.read_bytes(), 'MP3', {}))
        first_backup = (self.path.parent / (self.path.name + tags.BACKUP_SUFFIX)).read_bytes()
        self.save(['title'])
        self.assertEqual((self.path.parent / (self.path.name + tags.BACKUP_SUFFIX)).read_bytes(), first_backup)
        storage.restore(self.path, self.root, self.root / 'backups', storage.revision(self.path))
        self.assertEqual(self.path.read_bytes(), original)

    def preserved(self, raw):
        path = self.root / 'original.mp3'
        path.write_bytes(raw)
        return tags.id3_preserved_frames(str(path), {'title', 'artist', 'album'})

    def test_v24_multivalue(self):
        self.check_version(4)

    def test_v23_multivalue(self):
        self.check_version(3)

    def test_unselected_artists(self):
        self.seed(4)
        self.save(['title'])
        self.assertEqual(ID3(self.path)['TPE1'].text, ['Elvis Presley', 'Guest Artist'])

    def test_untagged_defaults_to_v24(self):
        ID3(self.path).delete(self.path)
        self.save()
        self.assertEqual(self.path.read_bytes()[:4], b'ID3\x04')

    def test_v22_upgrades_to_v24(self):
        # Genuine v2.2 TT2 frame, followed by generated MPEG audio.
        raw = self.path.read_bytes()
        audio = tags._audio_bytes(raw, 'MP3', {})
        payload = b'\x00Old title'
        frame = b'TT2' + len(payload).to_bytes(3, 'big') + payload
        size = len(frame)
        header = b'ID3\x02\x00\x00' + bytes([(size >> 21) & 127, (size >> 14) & 127, (size >> 7) & 127, size & 127])
        self.path.write_bytes(header + frame + audio)
        self.save()
        self.assertEqual(self.path.read_bytes()[:4], b'ID3\x04')

    def test_unselected_frame_loss_is_blocked(self):
        self.seed(4)
        original = self.path.read_bytes()
        write = tags.write_file
        def damage(path, *args, **kwargs):
            write(path, *args, **kwargs)
            id3 = ID3(path)
            id3.delall('TXXX:Custom values')
            id3.save(path)
        with patch.object(tags, 'write_file', side_effect=damage):
            with self.assertRaises(storage.StorageError):
                self.save()
        self.assertEqual(self.path.read_bytes(), original)

    def test_audio_damage_is_blocked(self):
        self.seed(4)
        original = self.path.read_bytes()
        write = tags.write_file
        def damage(path, *args, **kwargs):
            write(path, *args, **kwargs)
            with open(path, 'ab') as stream:
                stream.write(b'audio damage')
        with patch.object(tags, 'write_file', side_effect=damage):
            with self.assertRaisesRegex(storage.StorageError, '오디오'):
                self.save()
        self.assertEqual(self.path.read_bytes(), original)

    def test_identifier_update(self):
        self.seed(4)
        result = storage.save(self.path, self.root, self.root / 'backups',
                              {'title': 'New title'}, ['title'], False,
                              storage.revision(self.path),
                              ids=tags.Ids(mb_artist_ids=['new-id'], itunes_artist_id='123'))
        self.assertEqual(result['status'], 'saved')
        info = tags.read_file(str(self.path))
        self.assertEqual(info.ids.mb_artist_ids, ['new-id'])
        self.assertEqual(info.ids.itunes_artist_id, '123')


if __name__ == '__main__':
    unittest.main(verbosity=2)
