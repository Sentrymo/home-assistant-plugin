"""Helpers for Sentrymo places (user-defined geofence areas)."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any
import unicodedata

EVENT_PLACE_ENTERED = "sentrymo_place_entered"
EVENT_PLACE_LEFT = "sentrymo_place_left"


def _slug(value: str) -> str:
    """Return an ASCII slug used only when the backend sends no place id."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")


def place_key(place_id: Any, name: str) -> str:
    """Return a stable key for a place, preferring its backend id."""
    if isinstance(place_id, (int, str)) and str(place_id).strip():
        return str(place_id).strip()
    return f"name_{_slug(name) or 'place'}"


def _vehicle_section(vehicle: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    section = vehicle.get(key, {})
    return section if isinstance(section, Mapping) else {}


def vehicle_places(vehicle: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """Return the places the vehicle is currently in.

    ``None`` means the backend sent no place data (feature not available or
    the segment is missing), which is different from an empty list (vehicle
    is outside every place).
    """
    state = _vehicle_section(vehicle, "state")
    location = _vehicle_section(vehicle, "location")

    details = state.get("place_details")
    if isinstance(details, list):
        items = [
            (item.get("id"), item.get("name"), item.get("icon"))
            for item in details
            if isinstance(item, Mapping)
        ]
    else:
        names = state.get("places")
        if names is None:
            names = location.get("places")
        if isinstance(names, str):
            names = names.split(",")
        if not isinstance(names, list):
            return None
        items = [(None, name, None) for name in names]

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for place_id, raw_name, icon in items:
        name = str(raw_name).strip() if raw_name is not None else ""
        if not name:
            continue
        key = place_key(place_id, name)
        if key in seen:
            continue
        seen.add(key)
        place: dict[str, Any] = {"key": key, "id": place_id, "name": name}
        if isinstance(icon, str) and icon:
            place["icon"] = icon
        result.append(place)
    return result


def place_changes(
    previous: Mapping[str, Mapping[str, Any]] | None,
    current: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Return (entered, left) places between two known place sets.

    Unknown data on either side yields no changes, so startup, restarts and
    outages never fire enter/leave events.
    """
    if previous is None or current is None:
        return [], []
    entered = [place for key, place in current.items() if key not in previous]
    left = [place for key, place in previous.items() if key not in current]
    return entered, left
