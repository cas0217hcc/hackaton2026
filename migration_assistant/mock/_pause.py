import time


def pause(scale: float, seconds: float) -> None:
    """Wait seconds * scale, so loading states are visible in mock mode. A scale of 0 (the tests) never waits."""
    if scale > 0:
        time.sleep(seconds * scale)
