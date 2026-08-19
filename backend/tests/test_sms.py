import base64
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from app.sms import (
    SMSConfigurationError,
    SMSDeliveryError,
    TwilioSMSProvider,
    get_sms_provider,
)


def test_no_configured_sms_provider_uses_demo_mode() -> None:
    config = SimpleNamespace(sms_provider="")

    assert get_sms_provider(config) is None


def test_incomplete_twilio_configuration_is_rejected() -> None:
    config = SimpleNamespace(
        sms_provider="twilio",
        twilio_account_sid="",
        twilio_auth_token="",
        twilio_from_number="",
    )

    with pytest.raises(SMSConfigurationError, match="TWILIO_ACCOUNT_SID"):
        get_sms_provider(config)


def test_twilio_provider_sends_expected_message() -> None:
    account_sid = "AC" + "a" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == (
            "https://api.twilio.com/2010-04-01/Accounts/"
            f"{account_sid}/Messages.json"
        )
        credentials = base64.b64encode(
            f"{account_sid}:test-auth-token".encode()
        ).decode()
        assert request.headers["Authorization"] == f"Basic {credentials}"
        form = parse_qs(request.content.decode())
        assert form["To"] == ["+972500000004"]
        assert form["From"] == ["+15005550006"]
        assert "123456" in form["Body"][0]
        assert "10 minutes" in form["Body"][0]
        return httpx.Response(201, json={"status": "queued"})

    provider = TwilioSMSProvider(
        account_sid=account_sid,
        auth_token="test-auth-token",
        from_number="+15005550006",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )

    provider.send_verification_code("+972500000004", "123456")


def test_twilio_provider_wraps_http_failure() -> None:
    provider = TwilioSMSProvider(
        account_sid="AC" + "a" * 32,
        auth_token="test-auth-token",
        from_number="+15005550006",
        timeout_seconds=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(503, json={"message": "unavailable"})
        ),
    )

    with pytest.raises(SMSDeliveryError):
        provider.send_verification_code("+972500000004", "123456")
