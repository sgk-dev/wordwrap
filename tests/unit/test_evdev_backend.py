"""Unit tests for SgkEvdevHotkeyListener ring-buffer logic."""

import time
from unittest.mock import MagicMock, patch
import pytest

# Mock evdev before importing SgkEvdevHotkeyListener
with patch('evdev.InputDevice'), patch('evdev.ecodes'):
    from sgk_wordwrap.input.evdev_backend import SgkEvdevHotkeyListener, _sgk_keycode_to_char

@pytest.fixture
def listener():
    with patch('sgk_wordwrap.input.evdev_backend._sgk_parse_hotkey', return_value=(set(), "z")):
        return SgkEvdevHotkeyListener("ctrl+shift+z")

def test_keycode_to_char():
    import evdev
    # We need to mock ecodes specifically for the test to work if evdev is not installed or different
    with patch('evdev.ecodes') as mock_ecodes:
        mock_ecodes.KEY_A = 30
        mock_ecodes.KEY_SPACE = 57
        assert _sgk_keycode_to_char(30) == "a"
        assert _sgk_keycode_to_char(57) == " "
        assert _sgk_keycode_to_char(999) is None

def test_buffer_append_and_get_word(listener):
    import evdev
    # Manually populate buffer
    with patch('sgk_wordwrap.input.evdev_backend._sgk_keycode_to_char') as mock_ktc:
        def side_effect(code):
            mapping = {30: "t", 31: "e", 32: "s", 33: "t", 57: " "}
            return mapping.get(code)
        mock_ktc.side_effect = side_effect
        
        now = time.monotonic()
        # "test "
        listener._key_buffer.append((30, now))
        listener._key_buffer.append((31, now))
        listener._key_buffer.append((32, now))
        listener._key_buffer.append((33, now))
        
        assert listener.sgk_get_last_word() == "test"
        
        # Add space and another word
        listener._key_buffer.append((57, now))
        listener._key_buffer.append((30, now)) # 't'
        assert listener.sgk_get_last_word() == "t"

def test_buffer_timeout(listener):
    # Manually populate with old timestamp
    listener._key_buffer.append((30, time.monotonic() - 10.0)) # 10s ago
    assert listener.sgk_get_last_word() == ""

def test_clear_buffer(listener):
    listener._key_buffer.append((30, time.monotonic()))
    listener.sgk_clear_buffer()
    assert len(listener._key_buffer) == 0
    assert listener.sgk_get_last_word() == ""
