from __future__ import annotations

from typing import Protocol

import httpx

from app.config import Settings, settings


class SMSConfigurationError(RuntimeError):
    pass


class SMSDeliveryError(RuntimeError):
    pass


class SMSProvider(Protocol):
    def send_verification_code(self, phone: str, code: str) -> None: ...


class TwilioSMSProvider:
    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def send_verification_code(self, phone: str, code: str) -> None:
        message = (
            f"Your PlacePulse verification code is {code}. "
            "It expires in 10 minutes."
        )
        url = (
            "https://api.twilio.com/2010-04-01/Accounts/"
            f"{self.account_sid}/Messages.json"
        )

        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    url,
                    auth=httpx.BasicAuth(self.account_sid, self.auth_token),
                    data={
                        "To": phone,
                        "From": self.from_number,
                        "Body": message,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SMSDeliveryError("The SMS provider rejected the message") from exc


def get_sms_provider(
    config: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
) -> SMSProvider | None:
    config = config or settings
    provider_name = config.sms_provider.strip().lower()
    if not provider_name:
        return None
    if provider_name != "twilio":
        raise SMSConfigurationError(
            f"Unsupported SMS_PROVIDER value: {config.sms_provider}"
        )

    required_values = {
        "TWILIO_ACCOUNT_SID": config.twilio_account_sid,
        "TWILIO_AUTH_TOKEN": config.twilio_auth_token,
        "TWILIO_FROM_NUMBER": config.twilio_from_number,
    }
    missing = [name for name, value in required_values.items() if not value.strip()]
    if missing:
        raise SMSConfigurationError(
            f"Missing Twilio configuration: {', '.join(missing)}"
        )

    return TwilioSMSProvider(
        account_sid=config.twilio_account_sid,
        auth_token=config.twilio_auth_token,
        from_number=config.twilio_from_number,
        timeout_seconds=config.sms_timeout_seconds,
        transport=transport,
    )
