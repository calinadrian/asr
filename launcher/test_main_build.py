"""Main release contracts: preserve NPC data and reject incomplete asset feeds."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import game_release
import main_build


class MainBuildTests(unittest.TestCase):
    def test_photo_only_publish_cannot_remove_story_npcs(self):
        with patch.object(game_release.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'retain story NPC fixes'):
                game_release.publish_zone_photos()
            run.assert_not_called()

    def test_game_release_refuses_every_missing_or_changed_archive(self):
        required = main_build.required_data()
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            for name in required:
                for mode in ('missing', 'changed'):
                    entries = [dict(name=n, sha256=('wrong' if n == name else h))
                               for n, h in required.items() if mode != 'missing' or n != name]
                    def download(*args, **kwargs):
                        (folder / 'patches.json').write_text(json.dumps(dict(patches=entries)))
                    with self.subTest(archive=name, mode=mode), patch.object(game_release.subprocess, 'run', download):
                        with self.assertRaises(ValueError):
                            game_release.require_live_data('game', folder)

    def test_missing_local_archive_is_rejected_before_upload(self):
        with tempfile.TemporaryDirectory() as scratch, patch.object(game_release, 'upload') as upload:
            with self.assertRaisesRegex(ValueError, 'reviewed'):
                game_release.publish_data(scratch)
            upload.assert_not_called()


if __name__ == '__main__':
    unittest.main()
