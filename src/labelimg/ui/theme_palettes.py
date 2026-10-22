"""Color math and accent presets shared by every appearance mode."""

from dataclasses import dataclass
import re


def rgb(color):
    return tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))


def blend(foreground, background, amount):
    return "#" + "".join(
        f"{round(a*amount+b*(1-amount)):02X}"
        for a, b in zip(rgb(foreground), rgb(background))
    )


def luminance(color):
    values = [v / 255 for v in rgb(color)]
    values = [
        v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values
    ]
    return sum(v * w for v, w in zip(values, (0.2126, 0.7152, 0.0722)))


def contrast_ratio(first, second):
    a, b = sorted((luminance(first), luminance(second)))
    return (b + 0.05) / (a + 0.05)


def readable(color, backgrounds, minimum=4.6):
    if min(contrast_ratio(color, b) for b in backgrounds) >= minimum:
        return color
    target = max(
        ("#000000", "#FFFFFF"),
        key=lambda c: min(contrast_ratio(c, b) for b in backgrounds),
    )
    low, high = 0.0, 1.0
    for _ in range(24):
        middle = (low + high) / 2
        trial = blend(target, color, middle)
        if min(contrast_ratio(trial, b) for b in backgrounds) >= minimum:
            high = middle
        else:
            low = middle
    return blend(target, color, high)


@dataclass(frozen=True)
class AccentPreset:
    identifier: str
    name_en: str
    name_zh: str
    color: str

    def __post_init__(self):
        if (
            not self.identifier
            or not self.name_en
            or not self.name_zh
            or not re.fullmatch(r"#[0-9a-fA-F]{6}", self.color)
        ):
            raise ValueError(
                "An accent needs an identifier, bilingual names and an RGB color"
            )


_accents = {
    a.identifier: a
    for a in (
        AccentPreset("plum", "Plum", "紫灰", "#756B9E"),
        AccentPreset("blue", "Blue", "蓝色", "#2E6EAD"),
        AccentPreset("teal", "Teal", "青绿", "#247C78"),
        AccentPreset("green", "Green", "绿色", "#3C805B"),
        AccentPreset("amber", "Amber", "琥珀", "#A46D28"),
        AccentPreset("orange", "Orange", "橙色", "#B86537"),
        AccentPreset("rose", "Rose", "玫红", "#B05B78"),
        AccentPreset("slate", "Slate", "石板灰", "#5C7287"),
    )
}


def available_accents():
    return tuple(_accents.values())


def register_accent(accent):
    if not isinstance(accent, AccentPreset):
        raise TypeError("register_accent requires AccentPreset")
    if accent.identifier in _accents:
        raise ValueError("Accent identifier is already registered")
    _accents[accent.identifier] = accent


def appearance_colors(base, mode, accent_id):
    if mode not in ("light", "dark"):
        raise ValueError("Resolve system mode before building its palette")
    preset = _accents[accent_id]
    dark = mode == "dark"
    colors = dict(base)
    colors.update(
        surface="#242A34" if dark else "#FFFFFF",
        workspace_gutter="#141820" if dark else "#EBEEF3",
        panel_header="#2A313C" if dark else "#F5F6F9",
        panel_border="#505C6D" if dark else "#C4CBD5",
        background="#1B2028" if dark else "#F5F6F9",
        text="#EBEFF6" if dark else "#253047",
        divider="#37414F" if dark else "#E2E7EF",
        disabled_background="#2B323E" if dark else "#F0F2F6",
        hover_overlay="#CED6E4" if dark else "#929292",
        preview_background="#11151B" if dark else "#202428",
    )
    bodies = (colors["surface"], colors["background"])
    accent = readable(preset.color, bodies)
    for _ in range(8):
        selected = blend(accent, colors["surface"], 0.20 if dark else 0.10)
        adjusted = readable(accent, (*bodies, selected))
        if adjusted == accent:
            break
        accent = adjusted
    selected = blend(accent, colors["surface"], 0.20 if dark else 0.10)
    hover = blend("#FFFFFF" if dark else "#000000", accent, 0.10)
    colors.update(accent=accent, accent_hover=hover, selected=selected)
    colors["on_accent"] = max(
        ("#FFFFFF", "#101820"),
        key=lambda c: min(contrast_ratio(c, b) for b in (accent, hover)),
    )
    colors["accent_border"] = readable(
        blend(accent, colors["surface"], 0.65), (*bodies, selected), 3.05
    )
    colors["border"] = readable("#667386" if dark else "#96A3B4", bodies, 3.05)
    colors["disabled_text"] = readable(
        "#8490A2" if dark else "#929AA6", (colors["disabled_background"],), 4.6
    )
    colors["danger"] = readable("#F08D9C" if dark else "#A33F55", bodies)
    colors["warning"] = readable("#E7B871" if dark else "#8C641F", bodies)
    colors["review_verified_foreground"] = readable(
        "#6FE6A0" if dark else "#176B37", bodies
    )
    colors["review_questioned_foreground"] = readable(
        "#FFD078" if dark else "#885100", bodies
    )
    for role, initial in (
        ("icon_file", "#87ADDF" if dark else "#5677A6"),
        ("icon_image", "#78BEB7" if dark else "#4F8582"),
        ("icon_success", "#8CC79D" if dark else "#5F8468"),
        ("icon_view", "#A0B2C9" if dark else "#64788F"),
    ):
        tone = readable(initial, bodies, 3.2)
        tint = blend(tone, colors["surface"], 0.17 if dark else 0.14)
        colors[role] = readable(tone, (*bodies, tint), 3.05)
        colors[role + "_tint"] = tint
    colors.update(
        icon_preference=accent,
        icon_preference_tint=selected,
        icon_annotation_tint=selected,
        icon_warning_tint=blend(colors["warning"], colors["surface"], 0.16),
        icon_danger_tint=blend(colors["danger"], colors["surface"], 0.16),
        canvas_verified=blend(colors["icon_success"], colors["background"], 0.14),
        canvas_questioned=blend(colors["warning"], colors["background"], 0.14),
    )
    all_bodies = (
        *bodies,
        selected,
        colors["canvas_verified"],
        colors["canvas_questioned"],
        colors["panel_header"],
    )
    colors["text"] = readable(colors["text"], all_bodies)
    colors["muted"] = readable("#A7B3C5" if dark else "#68758A", all_bodies)
    colors["icon_structure"] = colors["muted"]
    colors["preview_border"] = readable(
        colors["muted"], (colors["preview_background"],), 3.05
    )
    colors["danger_border"] = readable(
        blend(colors["danger"], colors["surface"], 0.65), bodies, 3.05
    )
    # File selection needs a persistent, opaque fill, distinct from subtle
    # control/chip selection. Never fade a stylesheet Highlight a second time.
    colors["selection_background"] = blend(accent, colors["surface"], 0.16 if dark else 0.14)
    colors["selection_border"] = blend(accent, colors["surface"], 0.32 if dark else 0.38)
    colors["selection_foreground"] = readable(
        colors["text"], (colors["selection_background"],)
    )
    return colors
