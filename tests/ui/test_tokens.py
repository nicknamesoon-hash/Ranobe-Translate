import re

from ranobe.core.models import NoteType, SegmentStatus
from ranobe.ui.theme.tokens import NOTE_COLORS, STATUS_COLORS, Durations, pick

HEX = re.compile(r"#[0-9A-F]{6}")


def test_every_status_and_note_type_has_light_and_dark_colors():
    assert set(STATUS_COLORS) == set(SegmentStatus)
    assert set(NOTE_COLORS) == set(NoteType)
    for light, dark in [*STATUS_COLORS.values(), *NOTE_COLORS.values()]:
        assert HEX.fullmatch(light) and HEX.fullmatch(dark) and light != dark


def test_reduce_motion_zeroes_durations():
    assert Durations.for_motion(True) == Durations(0, 0, 0)
    assert Durations.for_motion(False).slow == 400
    assert pick(("#000000", "#FFFFFF"), dark=True) == "#FFFFFF"
