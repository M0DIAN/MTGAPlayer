"""Read-only pixel readiness within one immutable logical context."""
import copy
import time
from . import markers
from .native import NativeBlocked


def visual_context(view):
    # Freshness timestamps may advance without changing the logical state.
    # Everything that binds coordinates or confirms effects must stay fixed.
    return copy.deepcopy({key: value for key, value in view.items()
                          if key not in {'last_observed', 'valid_until', 'valid'}})


def wait_for_frame(adapter, nonce, sample, deadline, required=(), stop=lambda: False, expected=None):
    """Return (frame, locations, current) without ever dispatching input.

    Only absent pixels / old visual context can be retried. Every attempt
    samples state before AND after capture/decoding, keeps the original bound
    context, and observes the same deadline and state validity horizon.
    """
    binding = visual_context(expected) if expected is not None else None

    def current():
        nonlocal binding
        if stop():
            raise InterruptedError('cancelled')
        if time.monotonic() >= deadline:
            raise TimeoutError('visual_readiness_timeout')
        adapter.check()  # Focus/PID/HWND/nonce/DPI/takeover errors never retry.
        view = sample()
        if not view.get('valid'):
            raise NativeBlocked('invalid_or_partial_visual_state')
        if time.monotonic() >= min(deadline, view['valid_until']):
            raise TimeoutError('visual_readiness_timeout')
        signature = visual_context(view)
        if binding is None:
            binding = signature
        elif signature != binding:
            raise NativeBlocked('visual_context_changed')
        if stop():
            raise InterruptedError('cancelled')
        adapter.check()  # Sampling must not hide a focus/stop/takeover change.
        return view

    while True:
        view = current()
        frame = adapter.capture()
        ready = False
        try:
            locations = markers.locate(frame, view['layout'], markers.tag(nonce, view))
            ready = all(obj in locations for obj in required)
        except ValueError as exc:
            if str(exc) not in {'harness_header_not_visible', 'stale_visual_context'}:
                raise  # Ambiguity and unrecognized decoder errors are terminal.
        after = current()
        if ready:
            return frame, locations, after
        remaining = min(deadline, after['valid_until']) - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('visual_readiness_timeout')
        time.sleep(min(0.02, remaining))
