import pytest
from pydantic import ValidationError

from app.schemas import KnockSendPayload


pytestmark = [pytest.mark.unit, pytest.mark.security]


def test_user_text_rejects_control_characters_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        KnockSendPayload.model_validate(
            {"type": "message", "text": "hello\u0000world"}
        )
    with pytest.raises(ValidationError):
        KnockSendPayload.model_validate(
            {"type": "message", "text": "hello", "unexpected": True}
        )
