from sqlalchemy.orm import Session

from app.models import Place


UNKNOWN_PLACE_LABEL = "Unknown place"


def place_display_name(db: Session, place: Place | None) -> str:
    if place is None:
        return UNKNOWN_PLACE_LABEL

    parent = (
        db.get(Place, place.parent_place_id)
        if place.parent_place_id is not None
        else None
    )
    place_parts = [place.name]
    if parent is not None and parent.name.casefold() != place.name.casefold():
        place_parts.append(parent.name)

    locality = place.locality
    current = parent
    visited = {place.id}
    while locality is None and current is not None and current.id not in visited:
        visited.add(current.id)
        locality = current.locality
        current = (
            db.get(Place, current.parent_place_id)
            if current.parent_place_id is not None
            else None
        )

    label = " · ".join(place_parts)
    if locality and all(locality.casefold() != name.casefold() for name in place_parts):
        return f"{label}, {locality}"
    return label
