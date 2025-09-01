# tests/test_labeling.py
import pytest

# Mirror the project labeling function so tests don't depend on DB.
def label_row(score, read, dropped, not_interested):
    if score is not None and score >= 8:
        return 1
    if read == -1:
        return 1
    if dropped == 1 or not_interested == 1 or (score is not None and score <= 4):
        return 0
    return None

@pytest.mark.parametrize(
    "score,read,dropped,not_interested,expected",
    [
        (9,   0, 0, 0, 1),   # high score => positive
        (None,-1,0, 0, 1),   # finished => positive
        (3,   0, 0, 0, 0),   # low score => negative
        (None,0, 1, 0, 0),   # dropped => negative
        (None,0, 0, 1, 0),   # not interested => negative
        (None,0, 0, 0, None) # no signal => unlabeled
    ]
)
def test_label_row(score, read, dropped, not_interested, expected):
    assert label_row(score, read, dropped, not_interested) == expected
