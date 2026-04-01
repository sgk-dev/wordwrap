"""Character mapping engine for keyboard layout conversion.

Loads JSON map files and provides bidirectional conversion between layouts.
Unrecognized characters pass through unchanged (no data loss).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_BUILTIN_MAPS_DIR = Path(__file__).parent / "data"


class SgkLayoutMap(NamedTuple):
    name: str
    from_layout: str
    to_layout: str
    description: str
    forward: dict[str, str]   # from_layout → to_layout
    reverse: dict[str, str]   # to_layout → from_layout


class SgkLayoutMapper:
    """Loads layout map files and converts text between layouts."""

    def __init__(self, custom_maps_dir: str | Path | None = None) -> None:
        self._maps: dict[tuple[str, str], SgkLayoutMap] = {}
        self._custom_dir: Path | None = (
            Path(custom_maps_dir).expanduser() if custom_maps_dir else None
        )

    def sgk_load_maps(self) -> None:
        """Load all built-in and custom JSON map files."""
        self._maps.clear()
        self._sgk_load_dir(_BUILTIN_MAPS_DIR)
        if self._custom_dir and self._custom_dir.is_dir():
            self._sgk_load_dir(self._custom_dir)
        _logger.info("sgk_maps_loaded", extra={"count": len(self._maps)})

    def _sgk_load_dir(self, directory: Path) -> None:
        for json_file in sorted(directory.glob("*.json")):
            try:
                self._sgk_load_file(json_file)
            except Exception as exc:
                _logger.warning(
                    "sgk_map_load_error",
                    extra={"file": str(json_file), "error": str(exc)},
                )

    def _sgk_load_file(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        forward: dict[str, str] = data["map"]
        reverse: dict[str, str] = {v: k for k, v in forward.items()}

        layout_map = SgkLayoutMap(
            name=data.get("name", path.stem),
            from_layout=data["from_layout"],
            to_layout=data["to_layout"],
            description=data.get("description", ""),
            forward=forward,
            reverse=reverse,
        )

        key_fwd = (layout_map.from_layout, layout_map.to_layout)
        key_rev = (layout_map.to_layout, layout_map.from_layout)
        self._maps[key_fwd] = layout_map
        self._maps[key_rev] = SgkLayoutMap(
            name=layout_map.name + "_reverse",
            from_layout=layout_map.to_layout,
            to_layout=layout_map.from_layout,
            description=layout_map.description + " (reverse)",
            forward=reverse,
            reverse=forward,
        )
        _logger.debug(
            "sgk_map_loaded",
            extra={"map_name": layout_map.name, "file": str(path)},
        )

    def sgk_convert(self, text: str, from_layout: str, to_layout: str) -> str:
        """Convert text from one layout to another.

        Characters with no mapping pass through unchanged.
        """
        key = (from_layout, to_layout)
        layout_map = self._maps.get(key)
        if layout_map is None:
            _logger.warning(
                "sgk_no_map_found",
                extra={"from": from_layout, "to": to_layout},
            )
            return text

        result = []
        for char in text:
            result.append(layout_map.forward.get(char, char))
        return "".join(result)

    def sgk_detect_likely_layout(self, text: str, candidates: list[str]) -> str | None:
        """Heuristic: return the layout whose characters dominate the text.

        Returns None if undetermined.
        """
        if not text or len(candidates) < 2:
            return None

        scores: dict[str, int] = {layout: 0 for layout in candidates}

        # Build reverse lookup: character → layout
        char_to_layout: dict[str, str] = {}
        for (from_l, _to_l), layout_map in self._maps.items():
            for char in layout_map.forward:
                char_to_layout[char] = from_l

        for char in text:
            if char.isalpha():
                layout = char_to_layout.get(char)
                if layout in scores:
                    scores[layout] += 1

        if not any(scores.values()):
            return None

        best = max(scores, key=lambda k: scores[k])
        return best if scores[best] > 0 else None

    def sgk_get_available_pairs(self) -> list[tuple[str, str]]:
        return list(self._maps.keys())

    def sgk_has_map(self, from_layout: str, to_layout: str) -> bool:
        return (from_layout, to_layout) in self._maps
