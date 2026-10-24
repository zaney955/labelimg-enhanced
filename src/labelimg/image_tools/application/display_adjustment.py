"""Session-only state for non-destructive Canvas display adjustment."""

from __future__ import annotations

from dataclasses import dataclass
import os


def _image_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _bounded(value):
    return max(-100, min(100, int(round(value))))


@dataclass(frozen=True)
class DisplayAdjustmentValues:
    brightness: int = 0
    contrast: int = 0

    def __post_init__(self):
        object.__setattr__(self, "brightness", _bounded(self.brightness))
        object.__setattr__(self, "contrast", _bounded(self.contrast))

    @property
    def neutral(self):
        return self == DisplayAdjustmentValues()


@dataclass(frozen=True)
class DisplayAdjustmentRestorePoint:
    master: DisplayAdjustmentValues
    overrides: tuple[tuple[str, DisplayAdjustmentValues], ...]


class CanvasDisplayAdjustmentSession:
    """Own one workspace's master values and absolute per-image overrides."""

    def __init__(self):
        self._workspace_key = None
        self._master = DisplayAdjustmentValues()
        self._overrides = {}
        self._source_tokens = {}
        self._restore_point = None
        self._master_gesture_before = None
        self._revision = 0

    @property
    def workspace_key(self):
        return self._workspace_key

    @property
    def master(self):
        return self._master

    @property
    def revision(self):
        return self._revision


    @property
    def has_adjustments(self):
        return not self._master.neutral or bool(self._overrides)

    @property
    def can_restore(self):
        return self._restore_point is not None

    def replace_workspace(self, workspace_key):
        workspace_key = str(workspace_key) if workspace_key is not None else None
        if workspace_key == self._workspace_key:
            return False
        self._workspace_key = workspace_key
        self._master = DisplayAdjustmentValues()
        self._overrides.clear()
        self._source_tokens.clear()
        self._restore_point = None
        self._master_gesture_before = None
        self._revision += 1
        return True

    def effective(self, path):
        if not path:
            return self._master
        return self._overrides.get(_image_key(path), self._master)

    def has_override(self, path):
        return bool(path) and _image_key(path) in self._overrides

    def begin_master_gesture(self):
        if self._master_gesture_before is None:
            self._master_gesture_before = DisplayAdjustmentRestorePoint(
                self._master,
                tuple(sorted(self._overrides.items())),
            )

    def set_master(self, values):
        values = _coerce_values(values)
        if self._master_gesture_before is None:
            self.begin_master_gesture()
        changed = values != self._master or bool(self._overrides)
        if not changed:
            return 0
        cleared = len(self._overrides)
        self._master = values
        self._overrides.clear()
        self._revision += 1
        return cleared

    def finish_master_gesture(self):
        before = self._master_gesture_before
        self._master_gesture_before = None
        if before is None or not before.overrides:
            self._restore_point = None
            return 0
        self._restore_point = before
        return len(before.overrides)

    def set_override(self, path, values):
        if not path:
            return False
        self._expire_restore()
        key = _image_key(path)
        values = _coerce_values(values)
        if self._overrides.get(key) == values:
            return False
        self._overrides[key] = values
        self._revision += 1
        return True

    def reset_current(self, path):
        self._expire_restore()
        if not path:
            return False
        removed = self._overrides.pop(_image_key(path), None)
        if removed is None:
            return False
        self._revision += 1
        return True

    def reset_all(self):
        self.begin_master_gesture()
        cleared = self.set_master(DisplayAdjustmentValues())
        self.finish_master_gesture()
        return cleared

    def restore_last_clear(self):
        restore_point = self._restore_point
        if restore_point is None:
            return False
        self._master = restore_point.master
        self._overrides = dict(restore_point.overrides)
        self._restore_point = None
        self._master_gesture_before = None
        self._revision += 1
        return True

    def observe_source(self, path, token):
        if not path:
            return False
        key = _image_key(path)
        previous = self._source_tokens.get(key)
        self._source_tokens[key] = token
        if previous is None or previous == token:
            return False
        self._expire_restore()
        removed = self._overrides.pop(key, None) is not None
        if removed:
            self._revision += 1
        return removed

    def source_pixels_replaced(self, paths):
        self._expire_restore()
        removed = 0
        for path in paths:
            key = _image_key(path)
            if self._overrides.pop(key, None) is not None:
                removed += 1
            self._source_tokens.pop(key, None)
        if removed:
            self._revision += 1
        return removed

    def rename_paths(self, mapping):
        self._expire_restore()
        changed = False
        for source, target in mapping.items():
            source_key = _image_key(source)
            target_key = _image_key(target)
            if source_key == target_key:
                continue
            if source_key in self._overrides:
                self._overrides[target_key] = self._overrides.pop(source_key)
                changed = True
            if source_key in self._source_tokens:
                self._source_tokens[target_key] = self._source_tokens.pop(
                    source_key
                )
                changed = True
        if changed:
            self._revision += 1
        return changed

    def remove_images(self, paths):
        self._expire_restore()
        removed = 0
        for path in paths:
            key = _image_key(path)
            if self._overrides.pop(key, None) is not None:
                removed += 1
            self._source_tokens.pop(key, None)
        if removed:
            self._revision += 1
        return removed


    def _expire_restore(self):
        self._restore_point = None
        self._master_gesture_before = None


def _coerce_values(values):
    if isinstance(values, DisplayAdjustmentValues):
        return values
    return DisplayAdjustmentValues(*values)


def contrast_factor(value):
    """Map the symmetric display slider to the committed-adjustment factor."""
    value = _bounded(value)
    if value < 0:
        return 1.0 + (value / 100.0) * 0.9
    return 1.0 + (value / 100.0) * 2.0
