"""Headless checks for track navigation on the startup radio."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import loadmusic
import radio


class TrackControlsTest(unittest.TestCase):
    def setUp(self):
        self.music = loadmusic.LoadMusic(mute=True)
        self.music.ok = True
        self.music.files = ["one.mp3", "two.mp3", "three.mp3", "four.mp3"]
        self.music.pos = 0

    def test_previous_wraps_and_rapid_presses_count_from_pending_track(self):
        self.music.skip(back=True)
        self.assertEqual(self.music.want, 3)
        self.music.skip()
        self.music.skip()
        self.assertEqual(self.music.want, 1)
        self.assertEqual(self.music.display_title, "… two")

    def test_stale_audio_never_replaces_current_song(self):
        music = self.music
        music.snd = "current"
        music.job = {"path": "two.mp3", "ok": True, "done": False, "out": "fake.wav"}
        music.skip()
        music.skip()
        with patch.object(music, "_prepare") as prepare, patch.object(loadmusic, "rl") as rl:
            music.update()
            prepare.assert_not_called()
            music.job["done"] = True
            music.update()
            prepare.assert_called_once_with("three.mp3")
            rl.load_sound.assert_not_called()
            rl.stop_sound.assert_not_called()
            self.assertEqual(music.snd, "current")

    def test_reversing_pending_skip_keeps_the_current_song(self):
        self.music.snd = "current"
        self.music.skip()
        self.music.skip(back=True)
        self.assertIsNone(self.music.want)
        self.assertEqual(self.music.snd, "current")

    def test_previous_button_accepts_click_while_bar_is_opening(self):
        music = self.music
        music._idle, music._exp = 0.0, 0.4
        with patch.object(loadmusic, "rl") as rl, patch.object(loadmusic, "font") as font:
            rl.get_screen_width.return_value = 960
            rl.get_screen_height.return_value = 540
            rl.get_frame_time.return_value = 0.0
            font.pointer.return_value = SimpleNamespace(x=75, y=16)
            font.clicked.return_value = True
            font.measure_text.return_value = 60
            music.widget(keys=False)
        self.assertEqual(music.want, 3)

    def test_in_car_radio_drops_stale_result_only_after_worker_finishes(self):
        receiver = radio.Radio.__new__(radio.Radio)
        receiver.gen = 2
        receiver._job = {"gen": 1, "done": False}
        receiver._ready = None
        receiver._collect()
        self.assertIsNotNone(receiver._job)
        receiver._job["done"] = True
        receiver._collect()
        self.assertIsNone(receiver._job)
        self.assertIsNone(receiver._ready)

    def test_in_car_radio_finishes_with_cyrillic_path_on_cp1252_console(self):
        path = "Песна.mp3"
        receiver = radio.Radio.__new__(radio.Radio)
        receiver._ready = receiver._job = None
        receiver._dir = "unused"
        receiver.user_off = False
        receiver.stations = [("station", [path])]
        receiver.orders = [[path]]
        receiver.sel = receiver.next_pos = receiver.gen = receiver._seq = 0
        with io.TextIOWrapper(io.BytesIO(), encoding="cp1252") as stdout:
            with redirect_stdout(stdout), patch.object(radio, "cut_fragment", return_value=True):
                receiver._prepare()
                receiver._job["thread"].join(timeout=2)
            self.assertTrue(receiver._job["done"])
        receiver._collect()
        self.assertEqual(receiver._ready["path"], path)

    def test_input_before_scan_finishes_is_replayed(self):
        music = self.music
        music.files = []
        music.pos = None
        music.setup = {"done": False}
        music.skip(back=True)
        music.update()
        self.assertEqual(music.early_skips, [True])
        music.setup = {"done": True, "result": ([("station", ["first.mp3", "last.mp3"])], ".")}
        with (
            patch.object(loadmusic, "rl"),
            patch.object(loadmusic.random, "shuffle"),
            patch.object(music, "_prepare") as prepare,
        ):
            music.update()
        prepare.assert_called_once_with("last.mp3")
        self.assertEqual(music.want, 1)


if __name__ == "__main__":
    unittest.main()
