import pytest

from app.inference import (
    InferenceError,
    explicitly_named_place,
    extract_json_object,
    image_decision,
    parse_guard_output,
)
from app.schemas import PlaceOption


def test_guard_safe_output_is_approved() -> None:
    decision = parse_guard_output("Safety: Safe\nCategories: None")

    assert decision.approved is True
    assert decision.categories == []


def test_guard_categories_are_mapped_to_application_categories() -> None:
    decision = parse_guard_output(
        "Safety: Unsafe\nCategories: Non-violent Illegal Acts, Jailbreak"
    )

    assert decision.approved is False
    assert decision.categories == ["illegal_activity", "prompt_injection"]


def test_guard_unknown_category_fails_closed() -> None:
    with pytest.raises(InferenceError):
        parse_guard_output("Safety: Unsafe\nCategories: Invented Category")


def test_router_json_can_be_extracted_from_model_formatting() -> None:
    assert extract_json_object(
        '```json\n{"place_id": 2, "reason": "Named"}\n```'
    ) == {"place_id": 2, "reason": "Named"}


def test_exact_place_name_is_routed_deterministically() -> None:
    places = [
        PlaceOption(place_id=1, name="Course Campus"),
        PlaceOption(place_id=2, name="Engineering Building", parent_place_id=1),
    ]

    matched = explicitly_named_place("Meet at Engineering Building", places)

    assert matched is not None
    assert matched.place_id == 2


def test_image_decision_rejects_unsafe_probability() -> None:
    decision = image_decision(
        [{"NSFL": 0.02, "NSFW": 0.91, "SFW": 0.07}], threshold=0.5
    )

    assert decision.approved is False
    assert decision.categories == ["sexual"]


def test_image_decision_uses_combined_unsafe_probability() -> None:
    decision = image_decision(
        [{"NSFL": 0.28, "NSFW": 0.27, "SFW": 0.45}], threshold=0.5
    )

    assert decision.approved is False
    assert decision.categories == ["violence_graphic"]
