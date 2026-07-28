#!/usr/bin/env python3
"""Offline tests.

    python -m unittest discover -s app -v

Almost everything in this app needs the network, so these cover the parts that
decide *what gets queued* — the two pure functions and the cancel path — where
being wrong is quiet and expensive.
"""
import os
import tempfile
import unittest

# Importing the app creates its output folders, so point them somewhere
# disposable before the import rather than seeding a real Downloads folder.
os.environ.setdefault("WTF_OUTPUT_DIR",
                      os.path.join(tempfile.gettempdir(), "wtf-test-output"))

import app as app_mod                                   # noqa: E402
from app import extract_urls, is_collection_url         # noqa: E402

OPTS = {"mode": "transcript", "model": "small.en", "language": "en", "srt": True}


class TestExtractUrls(unittest.TestCase):
    def test_single_url(self):
        self.assertEqual(extract_urls("https://youtu.be/abc"),
                         ["https://youtu.be/abc"])

    def test_newline_list(self):
        text = "https://a.com/1\nhttps://b.com/2\n\nhttps://c.com/3"
        self.assertEqual(extract_urls(text),
                         ["https://a.com/1", "https://b.com/2", "https://c.com/3"])

    def test_comma_separated(self):
        self.assertEqual(extract_urls("https://a.com/1, https://b.com/2"),
                         ["https://a.com/1", "https://b.com/2"])

    def test_numbered_list(self):
        self.assertEqual(extract_urls("1. https://a.com/1\n2. https://b.com/2"),
                         ["https://a.com/1", "https://b.com/2"])

    def test_links_embedded_in_prose(self):
        text = "Check out https://a.com/1 (great) and also https://b.com/2. Thanks!"
        self.assertEqual(extract_urls(text),
                         ["https://a.com/1", "https://b.com/2"])

    def test_strips_trailing_sentence_punctuation(self):
        self.assertEqual(extract_urls("https://a.com/watch?v=x_1."),
                         ["https://a.com/watch?v=x_1"])

    def test_keeps_balanced_trailing_paren(self):
        self.assertEqual(extract_urls("https://a.com/Foo_(bar)"),
                         ["https://a.com/Foo_(bar)"])

    def test_strips_unbalanced_trailing_paren(self):
        self.assertEqual(extract_urls("(see https://a.com/x)"),
                         ["https://a.com/x"])

    def test_dedupes_preserving_order(self):
        text = "https://b.com/2\nhttps://a.com/1\nhttps://b.com/2"
        self.assertEqual(extract_urls(text), ["https://b.com/2", "https://a.com/1"])

    def test_ignores_schemeless(self):
        self.assertEqual(extract_urls("youtube.com/watch?v=x"), [])

    def test_empty(self):
        self.assertEqual(extract_urls(""), [])
        self.assertEqual(extract_urls("   \n  "), [])
        self.assertEqual(extract_urls(None), [])


class TestIsCollectionUrl(unittest.TestCase):
    def test_watch_url_inside_a_playlist_is_a_single_video(self):
        # The one that matters: this is what you get clicking a video from
        # inside a playlist. Expanding it would queue the whole playlist.
        self.assertFalse(is_collection_url(
            "https://www.youtube.com/watch?v=abc&list=PL123"))

    def test_plain_watch_url(self):
        self.assertFalse(is_collection_url("https://www.youtube.com/watch?v=abc"))

    def test_short_url(self):
        self.assertFalse(is_collection_url("https://youtu.be/abc"))

    def test_unrelated_host(self):
        self.assertFalse(is_collection_url("https://example.com/podcast/ep1"))

    def test_playlist_url(self):
        self.assertTrue(is_collection_url(
            "https://www.youtube.com/playlist?list=PL123"))

    def test_handle_url(self):
        self.assertTrue(is_collection_url("https://www.youtube.com/@someone"))

    def test_channel_url(self):
        self.assertTrue(is_collection_url("https://www.youtube.com/channel/UC123"))

    def test_legacy_c_and_user_urls(self):
        self.assertTrue(is_collection_url("https://www.youtube.com/c/Someone"))
        self.assertTrue(is_collection_url("https://www.youtube.com/user/Someone"))

    def test_videos_tab(self):
        self.assertTrue(is_collection_url("https://www.youtube.com/@someone/videos"))


class TestCancel(unittest.TestCase):
    def setUp(self):
        app_mod.jobs.clear()

    def test_removing_a_pending_job_takes_it_out_of_the_queue(self):
        job = app_mod.make_job("https://a.com/1", OPTS)
        self.assertEqual(len(app_mod.snapshot()), 1)
        self.assertTrue(app_mod.cancel_job(job["id"]))
        self.assertTrue(job["cancelled"])
        self.assertEqual(job["status"], "removed")
        self.assertEqual(app_mod.snapshot(), [])

    def test_cancelling_twice_is_a_no_op(self):
        job = app_mod.make_job("https://a.com/1", OPTS)
        self.assertTrue(app_mod.cancel_job(job["id"]))
        self.assertFalse(app_mod.cancel_job(job["id"]))

    def test_cancelling_an_unknown_job_is_false(self):
        self.assertFalse(app_mod.cancel_job("nope"))

    def test_stop_all_clears_every_pending_item(self):
        for i in range(3):
            app_mod.make_job(f"https://a.com/{i}", OPTS)
        self.assertEqual(app_mod.stop_all(), 3)
        self.assertEqual(app_mod.snapshot(), [])

    def test_stop_all_leaves_finished_work_alone(self):
        done = app_mod.make_job("https://a.com/done", OPTS)
        done["status"] = "done"
        app_mod.make_job("https://a.com/pending", OPTS)
        self.assertEqual(app_mod.stop_all(), 1)
        self.assertEqual([i["status"] for i in app_mod.snapshot()], ["done"])

    def test_worker_skips_a_cancelled_job_without_running_it(self):
        job = app_mod.make_job("https://a.com/1", OPTS)
        job["cancelled"] = True          # as if stopped after it was queued
        ran = []
        orig = app_mod.run_job
        app_mod.run_job = ran.append
        try:
            app_mod.work_q.put(job)
            app_mod.work_q.join()
        finally:
            app_mod.run_job = orig
        self.assertEqual(ran, [])
        self.assertEqual(job["status"], "cancelled")

    def test_worker_runs_a_live_job(self):
        job = app_mod.make_job("https://a.com/1", OPTS)
        ran = []
        orig = app_mod.run_job
        app_mod.run_job = ran.append
        try:
            app_mod.work_q.put(job)
            app_mod.work_q.join()
        finally:
            app_mod.run_job = orig
        self.assertEqual(ran, [job])


class TestQueueSnapshot(unittest.TestCase):
    def setUp(self):
        app_mod.jobs.clear()

    def test_snapshot_is_ordered_by_submission(self):
        urls = [f"https://a.com/{i}" for i in range(5)]
        for u in urls:
            app_mod.make_job(u, OPTS)
        self.assertEqual([i["url"] for i in app_mod.snapshot()], urls)

    def test_title_defaults_to_a_readable_url(self):
        job = app_mod.make_job("https://www.youtube.com/watch?v=abc", OPTS)
        self.assertEqual(job["title"], "youtube.com/watch?v=abc")


if __name__ == "__main__":
    unittest.main()
