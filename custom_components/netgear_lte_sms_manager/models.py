"""Type stubs and data models for netgear_lte_sms_manager."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from eternalegypt.eternalegypt import Modem

from .const import LOGGER


@dataclass
class SMSMessage:
    """Represents an SMS message in the modem inbox."""

    id: int
    sender: str
    message: str
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DependencyError(Exception):
    pass


class EternalEgyptVersionError(DependencyError):
    pass


class ModemCommunicationError(DependencyError):
    pass


class NetgearLTECoreMissingError(DependencyError):
    pass


class ModemConnection:
    """Wrapper around eternalegypt.Modem for safe access with error handling."""

    def __init__(self, modem: Modem) -> None:
        if modem is None:
            raise ValueError("modem cannot be None")
        self._modem = modem

    async def get_sms_list(self) -> list[SMSMessage]:
        try:
            if not hasattr(self._modem, "information"):
                raise EternalEgyptVersionError(
                    "Modem.information method not found. eternalegypt version may be incompatible."
                )

            info = await self._modem.information()
            raw_list = info.sms if info and hasattr(info, "sms") else []

            sms_messages = []
            for sms in raw_list:
                try:
                    msg = SMSMessage(
                        id=int(sms.id),
                        sender=str(sms.sender) if hasattr(sms, "sender") else "Unknown",
                        message=str(sms.message) if hasattr(sms, "message") else "",
                        timestamp=str(sms.timestamp)
                        if hasattr(sms, "timestamp") and sms.timestamp
                        else None,
                    )
                    sms_messages.append(msg)
                except (AttributeError, ValueError, TypeError) as e:
                    LOGGER.warning("Failed to parse SMS, skipping: %s. Error: %s", sms, e)
                    continue

            return sms_messages

        except EternalEgyptVersionError:
            raise
        except AttributeError as ex:
            raise EternalEgyptVersionError(
                f"Modem API mismatch: {ex}. eternalegypt may have a breaking change."
            ) from ex
        except TimeoutError as ex:
            raise ModemCommunicationError(
                f"Timeout communicating with modem: {ex}"
            ) from ex
        except Exception as ex:
            raise ModemCommunicationError(
                f"Failed to fetch SMS: {type(ex).__name__}: {ex}"
            ) from ex

    async def send_sms(self, phone: str, message: str) -> None:
        try:
            if not hasattr(self._modem, "sms"):
                raise EternalEgyptVersionError("Modem.sms method not found.")
            LOGGER.debug("Sending SMS to %s", phone)
            await self._modem.sms(phone, message)
            LOGGER.info("SMS dispatched to %s (modem accepted)", phone)
        except EternalEgyptVersionError:
            raise
        except Exception as ex:
            raise ModemCommunicationError(
                f"Failed to send SMS to {phone}: {type(ex).__name__}: {ex}"
            ) from ex

    async def delete_sms(self, sms_id: int) -> None:
        try:
            if not hasattr(self._modem, "delete_sms"):
                raise EternalEgyptVersionError(
                    "Modem.delete_sms method not found. eternalegypt version may be incompatible."
                )
            await self._modem.delete_sms(sms_id)
        except EternalEgyptVersionError:
            raise
        except AttributeError as ex:
            raise EternalEgyptVersionError(
                f"Modem API mismatch in delete_sms: {ex}"
            ) from ex
        except Exception as ex:
            raise ModemCommunicationError(
                f"Failed to delete SMS {sms_id}: {type(ex).__name__}: {ex}"
            ) from ex

    async def delete_sms_batch(self, sms_ids: list[int]) -> int:
        deleted_count = 0
        errors = []

        for sms_id in sms_ids:
            try:
                await self.delete_sms(sms_id)
                deleted_count += 1
            except Exception as ex:
                errors.append((sms_id, str(ex)))
                LOGGER.warning("Failed to delete SMS %d: %s", sms_id, ex)

        if errors and deleted_count == 0:
            raise ModemCommunicationError(
                f"Failed to delete any SMS. Errors: {errors}"
            )

        if errors:
            LOGGER.warning(
                "Partial deletion: %d succeeded, %d failed. Errors: %s",
                deleted_count,
                len(errors),
                errors,
            )

        return deleted_count
