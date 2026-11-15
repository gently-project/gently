"""A line written after another is later than it.

The notebook lists newest first by ``created_at``, and an ask is answered by
a line written after it. A note takes its time from the clock when it is
made, and the clock on Windows ticks every few milliseconds: two lines
written back to back shared a time and were listed in the order of their
random ids. tests/test_inbox.py failed about one run in two on the rig's own
PC for it, and never on CI, whose clock is finer.

The store now gives a new line that falls inside the last line's tick the
next microsecond.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from gently.harness.memory.notebook import Note, NotebookStore, NoteKind


def _line(body: str, at: datetime) -> Note:
    return Note(id="", kind=NoteKind.OBSERVATION, body=body, created_at=at)


def test_lines_written_in_one_tick_keep_the_order_they_were_written_in(tmp_path):
    nb = NotebookStore(tmp_path)
    tick = datetime(2026, 11, 13, 14, 0, 0, 15000)
    ids = [nb.write_note(_line(f"line {n}", tick)) for n in range(5)]
    listed = [n.id for n in nb.query_notes()]
    assert listed == ids[::-1]  # newest first, every time
    times = [nb.get_note(i).created_at for i in ids]
    assert times == sorted(times) and len(set(times)) == 5
    # Moved by microseconds, not by anything a reader would see.
    assert times[-1] - tick == timedelta(microseconds=4)


def test_a_line_with_a_time_of_its_own_is_left_alone(tmp_path):
    nb = NotebookStore(tmp_path)
    now = datetime(2026, 11, 13, 14, 0, 0)
    nb.write_note(_line("today", now))
    # An older line brought in afterwards keeps its date.
    old = nb.write_note(_line("from last month", datetime(2026, 10, 2, 9, 30)))
    assert nb.get_note(old).created_at == datetime(2026, 10, 2, 9, 30)
    later = nb.write_note(_line("a minute on", now + timedelta(minutes=1)))
    assert nb.get_note(later).created_at == now + timedelta(minutes=1)


def test_writing_a_line_again_does_not_move_it(tmp_path):
    nb = NotebookStore(tmp_path)
    tick = datetime(2026, 11, 13, 14, 0, 0)
    first = nb.write_note(_line("first", tick))
    second = nb.write_note(_line("second", tick))
    note = nb.get_note(first)
    note.body = "first, corrected"
    nb.write_note(note)
    assert nb.get_note(first).created_at == tick
    assert [n.id for n in nb.query_notes()] == [second, first]
