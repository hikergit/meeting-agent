"""
Shared perception-source state — lets the caption and audio adapters coordinate.

The caption adapter is PRIMARY (it carries speaker names from Meet).
The audio adapter is a BACKUP that only transcribes when captions are NOT active.

We track the last time captions were seen ON. The audio adapter checks
`captions_recently_active()` and stays silent while captions are working,
taking over only after a grace period with no captions.
"""
import time

# Seconds captions can be absent before audio backup takes over.
CAPTION_GRACE = 6.0

_last_caption_on: float = 0.0


def mark_captions_on() -> None:
    """Called by the caption adapter each tick the Meet captions panel is present."""
    global _last_caption_on
    _last_caption_on = time.time()


def captions_recently_active() -> bool:
    return (time.time() - _last_caption_on) < CAPTION_GRACE
