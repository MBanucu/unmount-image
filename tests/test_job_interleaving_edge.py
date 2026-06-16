"""Edge case tests for concurrent/interleaved job events in udisksctl
monitor output.

When multiple operations happen concurrently (e.g. three loop devices are
unmounted in quick succession), UDisks2 jobs can interleave: a second job's
"Added" may arrive before the first job's "Removed".

This exercises the _MonitorParser's limitation: it tracks only one job at a
time via a boolean _in_job flag. When a second job is Added before the first
is Removed, the first job's accumulated data is silently discarded.
"""

import unittest

from unmount_image._monitor import _MonitorParser


class TestConcurrentJobInterleaving(unittest.TestCase):
    """Tests parser behaviour when concurrent jobs' events interleave."""

    def test_two_jobs_added_before_either_removed(self):
        """Real scenario: two filesystem-unmount jobs fire concurrently.
        Jobs 10851 and 10852 Added before either Completed/Removed."""
        p = _MonitorParser()

        # Job 1: unmount loop3
        p.feed('Added /org/freedesktop/UDisks2/jobs/10851')
        p.feed('    Operation:          filesystem-unmount')
        r1 = p.feed('    Objects:            '
                    '/org/freedesktop/UDisks2/block_devices/loop3')
        self.assertIsNotNone(r1)
        self.assertEqual(r1[1]['op'], 'filesystem-unmount')
        self.assertIn('loop3', r1[1]['objects'])

        # Job 2 Added before Job 1 Removed — parser resets
        p.feed('Added /org/freedesktop/UDisks2/jobs/10852')
        # Job 2 properties
        p.feed('    Operation:          filesystem-unmount')
        r2 = p.feed('    Objects:            '
                    '/org/freedesktop/UDisks2/block_devices/loop4')
        self.assertIsNotNone(r2)
        self.assertEqual(r2[1]['op'], 'filesystem-unmount')
        self.assertIn('loop4', r2[1]['objects'])

        # Job 1 completes (after Job 2 was added)
        p.feed('/org/.../jobs/10851: '
               'org.freedesktop.UDisks2.Job::Completed (true, \'\')')
        p.feed('Removed /org/freedesktop/UDisks2/jobs/10851')

        # Job 2 completes
        p.feed('/org/.../jobs/10852: '
               'org.freedesktop.UDisks2.Job::Completed (true, \'\')')
        p.feed('Removed /org/freedesktop/UDisks2/jobs/10852')

    def test_job_interleaved_with_property_changes(self):
        """A job's property changes and another device's events interleave.
        While _in_job and not _emitted, the parser's early return means
        interleaved device header lines do NOT update _current_device."""
        p = _MonitorParser()

        # Device context set
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')

        # Job added
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          filesystem-unmount')

        # Interleaved: a different device fires Properties Changed
        # But we are inside _in_job AND not _emitted, so the parser
        # checks the job property block first (returns None early)
        # and never reaches the _device_name_from_path check.
        p.feed('/org/.../block_devices/loop1: '
               'org.freedesktop.UDisks2.Filesystem: Properties Changed')
        # _current_device stays as 'loop0' — device extraction is skipped
        # while _in_job and not _emitted
        self.assertEqual(p._current_device, 'loop0')

        # Back to job properties — Objects arrives, now it emits
        r = p.feed('    Objects:            '
                   '/org/freedesktop/UDisks2/block_devices/loop0')
        self.assertIsNotNone(r)
        self.assertEqual(r[1]['op'], 'filesystem-unmount')

        # Now that _emitted=True, subsequent device lines WILL update context
        p.feed('/org/.../block_devices/loop1: '
               'org.freedesktop.UDisks2.Filesystem: Properties Changed')
        self.assertEqual(p._current_device, 'loop1')

    def test_three_concurrent_jobs(self):
        """Three unmount jobs — a real concurrency scenario."""
        p = _MonitorParser()

        # Setup device context
        p.feed('/org/.../block_devices/loop2: '
               'org.freedesktop.UDisks2.Block: Properties Changed')
        p.feed('  BackingFile:          /tmp/a.img')

        # Job A
        p.feed('Added /org/freedesktop/UDisks2/jobs/100')
        p.feed('    Operation:          filesystem-unmount')
        p.feed('    Objects:            '
               '/org/freedesktop/UDisks2/block_devices/loop2')

        # Job B (interleaved)
        p.feed('Added /org/freedesktop/UDisks2/jobs/101')
        p.feed('    Operation:          filesystem-unmount')
        p.feed('    Objects:            '
               '/org/freedesktop/UDisks2/block_devices/loop3')

        # Job C (interleaved)
        p.feed('Added /org/freedesktop/UDisks2/jobs/102')
        p.feed('    Operation:          filesystem-unmount')
        r = p.feed('    Objects:            '
                   '/org/freedesktop/UDisks2/block_devices/loop4')
        self.assertIsNotNone(r)
        self.assertEqual(r[1]['objects'],
                         '/org/freedesktop/UDisks2/block_devices/loop4')

    def test_mount_and_unmount_jobs_interleaved(self):
        """A mount and an unmount job for different devices fire
        concurrently."""
        p = _MonitorParser()

        # Mount job for loop0
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          filesystem-mount')
        r1 = p.feed('    Objects:            '
                    '/org/freedesktop/UDisks2/block_devices/loop0')
        self.assertEqual(r1[1]['op'], 'filesystem-mount')

        # Unmount job for loop1 — arrives before loop0 mount completes
        p.feed('Added /org/freedesktop/UDisks2/jobs/2')
        p.feed('    Operation:          filesystem-unmount')
        r2 = p.feed('    Objects:            '
                    '/org/freedesktop/UDisks2/block_devices/loop1')
        self.assertEqual(r2[1]['op'], 'filesystem-unmount')

    def test_cleanup_jobs_interleaved_with_user_jobs(self):
        """cleanup jobs (internal housekeeping) interleave with user
        operations. cleanup jobs have empty Objects in real output."""
        p = _MonitorParser()

        # User job
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          loop-setup')
        p.feed('    Objects:            '
               '/org/freedesktop/UDisks2/block_devices/loop0')
        self.assertTrue(p._emitted)

        # Cleanup job interleaved before first job completes
        # Real cleanup jobs have Objects with spaces but no path
        p.feed('Added /org/freedesktop/UDisks2/jobs/2')
        p.feed('    Operation:          cleanup')
        # cleanup has empty Objects line with spaces
        p.feed('    Objects:            ')
        # _OBJ_RE requires \S+, so purely whitespace Objects won't match.
        # Parser won't emit and _job_objects stays empty (falsy).
        self.assertFalse(p._emitted)
        p.feed('Removed /org/freedesktop/UDisks2/jobs/2')
        self.assertFalse(p._in_job)

    def test_job_removed_before_objects_seen(self):
        """Edge case: job Added then Removed before Objects property is seen.
        The parser exits job context, discarding the partial job."""
        p = _MonitorParser()
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          filesystem-mount')
        # Removed before Objects — parser exits job context
        p.feed('Removed /org/freedesktop/UDisks2/jobs/1')
        self.assertFalse(p._in_job)

    def test_concurrent_jobs_same_device(self):
        """Two jobs targeting the same device running concurrently.
        This should not happen in practice (UDisks2 serializes per device)
        but the parser should handle it."""
        p = _MonitorParser()

        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          filesystem-unmount')
        p.feed('    Objects:            '
               '/org/freedesktop/UDisks2/block_devices/loop0')

        p.feed('Added /org/freedesktop/UDisks2/jobs/2')
        p.feed('    Operation:          loop-delete')
        p.feed('    Objects:            '
               '/org/freedesktop/UDisks2/block_devices/loop0')

        # In practice, the monitor would need to re-emit on the second
        # job — but the parser already emitted for job 1 and resets state
        # for job 2.
        self.assertTrue(p._emitted)  # re-emitted for job 2

    def test_monitor_catches_second_job_after_first_removed(self):
        """Normal non-interleaved case: jobs complete before next starts."""
        p = _MonitorParser()

        # Job 1: full cycle
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          filesystem-mount')
        r1 = p.feed('    Objects:            '
                    '/org/freedesktop/UDisks2/block_devices/loop0')
        self.assertEqual(r1[1]['op'], 'filesystem-mount')
        p.feed('Removed /org/freedesktop/UDisks2/jobs/1')

        # Job 2: full cycle
        p.feed('Added /org/freedesktop/UDisks2/jobs/2')
        p.feed('    Operation:          filesystem-unmount')
        r2 = p.feed('    Objects:            '
                    '/org/freedesktop/UDisks2/block_devices/loop0')
        self.assertEqual(r2[1]['op'], 'filesystem-unmount')
        p.feed('Removed /org/freedesktop/UDisks2/jobs/2')

    def test_job_added_after_previousremoved_without_emission(self):
        """A job is Added and Removed without ever having Objects set,
        then a new job starts. Parser should handle cleanly."""
        p = _MonitorParser()

        # Job without Objects
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          cleanup')
        p.feed('Removed /org/freedesktop/UDisks2/jobs/1')
        self.assertFalse(p._emitted)

        # Next job starts fresh
        p.feed('Added /org/freedesktop/UDisks2/jobs/2')
        p.feed('    Operation:          filesystem-mount')
        r = p.feed('    Objects:            '
                   '/org/freedesktop/UDisks2/block_devices/loop0')
        self.assertIsNotNone(r)
        self.assertEqual(r[1]['op'], 'filesystem-mount')

    def test_operation_without_objects_does_not_emit(self):
        """A job has Operation but Objects is empty — should not emit.
        Real: cleanup jobs have empty Objects."""
        p = _MonitorParser()
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          cleanup')
        # Objects line exists but is empty
        r = p.feed('    Objects:')
        # _OBJ_RE matches '' — so _job_objects is set to ''
        # But should it emit? In the current code, '' is truthy-checked...
        # Actually let's check: _job_objects = '' is falsy, so it won't emit!
        self.assertIsNone(r)
        self.assertFalse(p._emitted)

    def test_empty_objects_field_no_emit(self):
        """Objects field is empty string; parser should not treat it as
        present."""
        p = _MonitorParser()
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          cleanup')
        self.assertIsNone(p.feed('    Objects:'))
