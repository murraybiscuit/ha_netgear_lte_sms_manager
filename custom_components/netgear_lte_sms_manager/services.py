"""Services for the Netgear LTE SMS Manager integration."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_COUNT_DELETED,
    ATTR_DRY_RUN,
    ATTR_HOST,
    ATTR_MESSAGES,
    ATTR_RETAIN_COUNT,
    ATTR_RETAIN_DAYS,
    ATTR_SMS_ID,
    ATTR_WHITELIST,
    CONF_WELCOME_MESSAGE,
    DEFAULT_DRY_RUN,
    DEFAULT_RETAIN_COUNT,
    DEFAULT_RETAIN_DAYS,
    DEFAULT_WELCOME_MESSAGE,
    DOMAIN,
    EVENT_CLEANUP_COMPLETE,
    EVENT_SMS_INBOX_LISTED,
    LOGGER,
    SERVICE_ADD_CONTACT,
    SERVICE_CLEANUP_INBOX,
    SERVICE_DELETE_SMS,
    SERVICE_GET_INBOX_JSON,
    SERVICE_LIST_INBOX,
    SERVICE_REMOVE_CONTACT,
    SERVICE_SEND_WELCOME,
    SERVICE_UPDATE_CONTACT,
)
from .helpers import (
    get_netgear_lte_entry,
    get_saved_options,
    load_contacts,
    normalize_number,
    parse_whitelist_options,
    save_contacts,
)
from .models import (
    EternalEgyptVersionError,
    ModemCommunicationError,
    ModemConnection,
    NetgearLTECoreMissingError,
)

LIST_INBOX_SCHEMA = vol.Schema({vol.Optional(ATTR_HOST): cv.string})

DELETE_SMS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_HOST): cv.string,
        vol.Required(ATTR_SMS_ID): vol.All(cv.ensure_list, [cv.positive_int]),
    }
)

CLEANUP_INBOX_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_HOST): cv.string,
        vol.Optional(ATTR_RETAIN_COUNT): vol.Any(None, cv.positive_int),
        vol.Optional(ATTR_RETAIN_DAYS): vol.Any(None, cv.positive_int),
        vol.Optional(ATTR_WHITELIST): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_DRY_RUN): cv.boolean,
    }
)

GET_INBOX_JSON_SCHEMA = vol.Schema({vol.Optional(ATTR_HOST): cv.string})

ADD_CONTACT_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("number"): cv.string,
        vol.Optional("send_welcome", default=False): cv.boolean,
        vol.Optional(ATTR_HOST): cv.string,
    }
)

UPDATE_CONTACT_SCHEMA = vol.Schema(
    {
        vol.Required("contact_id"): cv.string,
        vol.Required("name"): cv.string,
        vol.Required("number"): cv.string,
    }
)

REMOVE_CONTACT_SCHEMA = vol.Schema({vol.Required("contact_id"): cv.string})

SEND_WELCOME_SCHEMA = vol.Schema(
    {
        vol.Required("number"): cv.string,
        vol.Optional(ATTR_HOST): cv.string,
    }
)


async def _service_list_inbox(call: ServiceCall) -> None:
    hass = call.hass
    host = call.data.get(ATTR_HOST)
    try:
        entry = get_netgear_lte_entry(hass, host)
        modem = ModemConnection(entry.runtime_data.modem)
        LOGGER.info("Fetching SMS inbox from %s", entry.data.get("host"))
        sms_list = await modem.get_sms_list()
        event_data = {
            ATTR_HOST: entry.data.get("host"),
            ATTR_MESSAGES: [msg.to_dict() for msg in sms_list],
        }
        LOGGER.info("Found %d SMS messages in inbox, firing event", len(sms_list))
        hass.bus.async_fire(EVENT_SMS_INBOX_LISTED, event_data)
    except NetgearLTECoreMissingError as ex:
        raise ServiceValidationError(str(ex), translation_domain=DOMAIN) from ex
    except EternalEgyptVersionError as ex:
        raise ServiceValidationError(f"API compatibility issue detected: {ex}", translation_domain=DOMAIN) from ex
    except ModemCommunicationError as ex:
        raise ServiceValidationError(f"Failed to reach modem: {ex}", translation_domain=DOMAIN) from ex
    except Exception as ex:
        LOGGER.exception("Unexpected error in list_inbox service")
        raise ServiceValidationError(f"Unexpected error: {type(ex).__name__}", translation_domain=DOMAIN) from ex


async def _service_delete_sms(call: ServiceCall) -> None:
    hass = call.hass
    host = call.data.get(ATTR_HOST)
    sms_ids = call.data[ATTR_SMS_ID]
    try:
        entry = get_netgear_lte_entry(hass, host)
        modem = ModemConnection(entry.runtime_data.modem)
        LOGGER.info("Deleting %d SMS from %s", len(sms_ids), entry.data.get("host"))
        deleted_count = await modem.delete_sms_batch(sms_ids)
        LOGGER.info("Successfully deleted %d SMS", deleted_count)
    except NetgearLTECoreMissingError as ex:
        raise ServiceValidationError(str(ex), translation_domain=DOMAIN) from ex
    except EternalEgyptVersionError as ex:
        raise ServiceValidationError(f"API compatibility issue: {ex}", translation_domain=DOMAIN) from ex
    except ModemCommunicationError as ex:
        raise ServiceValidationError(f"Deletion error: {ex}", translation_domain=DOMAIN) from ex
    except Exception as ex:
        LOGGER.exception("Unexpected error in delete_sms service")
        raise ServiceValidationError(f"Unexpected error: {type(ex).__name__}", translation_domain=DOMAIN) from ex


async def _service_cleanup_inbox(call: ServiceCall) -> None:
    hass = call.hass
    host = call.data.get(ATTR_HOST)
    retain_count = call.data.get(ATTR_RETAIN_COUNT, DEFAULT_RETAIN_COUNT)
    retain_days = call.data.get(ATTR_RETAIN_DAYS, DEFAULT_RETAIN_DAYS)
    options = get_saved_options(hass)
    parsed = parse_whitelist_options(options)
    saved_numbers = parsed.get("phone_numbers", set())
    contacts = parsed.get("contacts", {})

    whitelist = set(saved_numbers)
    for c in contacts.values():
        if c.get("number"):
            whitelist.add(c["number"])
        if c.get("name"):
            whitelist.add(c["name"])

    call_whitelist = call.data.get(ATTR_WHITELIST, []) or []
    for w in call_whitelist:
        whitelist.add(w)
    dry_run = call.data.get(ATTR_DRY_RUN, DEFAULT_DRY_RUN)

    try:
        entry = get_netgear_lte_entry(hass, host)
        modem = ModemConnection(entry.runtime_data.modem)
        LOGGER.info("Fetching SMS inbox for cleanup from %s", entry.data.get("host"))
        sms_list = await modem.get_sms_list()

        def parse_ts(ts: str | None) -> datetime | None:
            if not ts:
                return None
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(ts, fmt)
                except Exception:
                    continue
            try:
                return datetime.fromisoformat(ts)
            except Exception:
                return None

        annotated = [(sms, parse_ts(getattr(sms, "timestamp", None))) for sms in sms_list]
        annotated.sort(key=lambda x: (x[1] is not None, x[1]), reverse=True)

        keep_ids: set[int] = set()
        kept = 0
        for sms, ts in annotated:
            if sms.sender in whitelist:
                keep_ids.add(sms.id)
                continue
            if retain_count and kept < retain_count:
                keep_ids.add(sms.id)
                kept += 1

        delete_candidates: list[int] = []
        if retain_days and retain_days > 0:
            cutoff = datetime.utcnow() - timedelta(days=retain_days)
            for sms, ts in annotated:
                if ts is None:
                    continue
                if ts < cutoff and sms.id not in keep_ids and sms.sender not in whitelist:
                    delete_candidates.append(sms.id)

        for sms, ts in reversed(annotated):
            if sms.id in keep_ids or sms.sender in whitelist:
                continue
            if sms.id not in delete_candidates and sms.id not in keep_ids:
                delete_candidates.append(sms.id)

        seen: set[int] = set()
        final_delete = []
        for sid in delete_candidates:
            if sid not in seen:
                seen.add(sid)
                final_delete.append(sid)

        if not final_delete:
            LOGGER.info("No messages to delete after applying cleanup policy")
            hass.bus.async_fire(
                EVENT_CLEANUP_COMPLETE,
                {ATTR_HOST: entry.data.get("host"), ATTR_COUNT_DELETED: 0, ATTR_WHITELIST: list(whitelist), ATTR_DRY_RUN: dry_run},
            )
            return

        if dry_run:
            LOGGER.info("Dry run cleanup, would delete %d messages", len(final_delete))
            hass.bus.async_fire(
                EVENT_CLEANUP_COMPLETE,
                {ATTR_HOST: entry.data.get("host"), ATTR_COUNT_DELETED: len(final_delete), ATTR_MESSAGES: final_delete, ATTR_WHITELIST: list(whitelist), ATTR_DRY_RUN: True},
            )
            return

        deleted_count = await modem.delete_sms_batch(final_delete)
        hass.bus.async_fire(
            EVENT_CLEANUP_COMPLETE,
            {ATTR_HOST: entry.data.get("host"), ATTR_COUNT_DELETED: deleted_count, ATTR_MESSAGES: final_delete, ATTR_WHITELIST: list(whitelist), ATTR_DRY_RUN: False},
        )
        LOGGER.info("Cleanup deleted %d messages", deleted_count)

    except NetgearLTECoreMissingError as ex:
        raise ServiceValidationError(str(ex), translation_domain=DOMAIN) from ex
    except EternalEgyptVersionError as ex:
        raise ServiceValidationError(f"API compatibility issue: {ex}", translation_domain=DOMAIN) from ex
    except ModemCommunicationError as ex:
        raise ServiceValidationError(f"Cleanup error: {ex}", translation_domain=DOMAIN) from ex
    except Exception as ex:
        LOGGER.exception("Unexpected error in cleanup_inbox service")
        raise ServiceValidationError(f"Unexpected error: {type(ex).__name__}", translation_domain=DOMAIN) from ex


async def _service_get_inbox_json(call: ServiceCall) -> dict[str, Any]:
    hass = call.hass
    host = call.data.get(ATTR_HOST)
    try:
        entry = get_netgear_lte_entry(hass, host)
        modem = ModemConnection(entry.runtime_data.modem)
        LOGGER.info("Fetching SMS inbox JSON from %s", entry.data.get("host"))
        sms_list = await modem.get_sms_list()
        return {ATTR_HOST: entry.data.get("host"), ATTR_MESSAGES: [msg.to_dict() for msg in sms_list]}
    except NetgearLTECoreMissingError as ex:
        raise ServiceValidationError(str(ex), translation_domain=DOMAIN) from ex
    except EternalEgyptVersionError as ex:
        raise ServiceValidationError(f"API compatibility issue: {ex}", translation_domain=DOMAIN) from ex
    except ModemCommunicationError as ex:
        raise ServiceValidationError(f"Modem error: {ex}", translation_domain=DOMAIN) from ex
    except Exception as ex:
        LOGGER.exception("Unexpected error in get_inbox_json service")
        raise ServiceValidationError(f"Unexpected error: {type(ex).__name__}", translation_domain=DOMAIN) from ex


async def _service_add_contact(call: ServiceCall) -> None:
    hass = call.hass
    name: str = call.data["name"].strip()
    number: str = normalize_number(call.data["number"])
    do_send_welcome: bool = call.data.get("send_welcome", False)
    host = call.data.get(ATTR_HOST)

    if not number:
        raise ServiceValidationError("Phone number contains no digits.")

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Netgear LTE SMS Manager is not configured.")
    sms_entry = entries[0]

    contacts = load_contacts(sms_entry.options)
    if any(normalize_number(c["number"]) == number for c in contacts):
        LOGGER.info("Contact %s (%s) already exists, skipping add", name, number)
    else:
        contacts.append({"uuid": str(uuid.uuid4()), "name": name, "number": number})
        hass.config_entries.async_update_entry(
            sms_entry, options={**sms_entry.options, "contacts": save_contacts(contacts)}
        )
        LOGGER.info("Added contact %s (%s)", name, number)

    if do_send_welcome:
        welcome_msg = sms_entry.options.get(CONF_WELCOME_MESSAGE, DEFAULT_WELCOME_MESSAGE)
        try:
            lte_entry = get_netgear_lte_entry(hass, host)
            modem = ModemConnection(lte_entry.runtime_data.modem)
            await modem.send_sms(number, welcome_msg)
            LOGGER.info("Sent welcome message to %s", number)
        except (NetgearLTECoreMissingError, EternalEgyptVersionError, ModemCommunicationError) as ex:
            LOGGER.warning("Failed to send welcome to %s: %s", number, ex)


async def _service_update_contact(call: ServiceCall) -> None:
    hass = call.hass
    contact_id: str = call.data["contact_id"]
    name: str = call.data["name"].strip()
    number: str = normalize_number(call.data["number"])

    if not name:
        raise ServiceValidationError("Name cannot be empty.")
    if not number:
        raise ServiceValidationError("Phone number contains no digits.")

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Netgear LTE SMS Manager is not configured.")
    sms_entry = entries[0]

    contacts = load_contacts(sms_entry.options)
    target = next((c for c in contacts if c.get("uuid") == contact_id), None)
    if not target:
        raise ServiceValidationError(f"Contact {contact_id} not found.")

    if any(c.get("uuid") != contact_id and normalize_number(c["number"]) == number for c in contacts):
        raise ServiceValidationError(f"Another contact already uses number {number}.")

    target["name"] = name
    target["number"] = number
    hass.config_entries.async_update_entry(
        sms_entry, options={**sms_entry.options, "contacts": save_contacts(contacts)}
    )
    LOGGER.info("Updated contact %s → %s (%s)", contact_id, name, number)


async def _service_remove_contact(call: ServiceCall) -> None:
    hass = call.hass
    contact_id: str = call.data["contact_id"]

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Netgear LTE SMS Manager is not configured.")
    sms_entry = entries[0]

    contacts = load_contacts(sms_entry.options)
    new_contacts = [c for c in contacts if c.get("uuid") != contact_id]
    if len(new_contacts) == len(contacts):
        LOGGER.warning("remove_contact: contact_id %s not found", contact_id)
        return

    hass.config_entries.async_update_entry(
        sms_entry, options={**sms_entry.options, "contacts": save_contacts(new_contacts)}
    )
    LOGGER.info("Removed contact %s", contact_id)


async def _service_send_welcome(call: ServiceCall) -> None:
    hass = call.hass
    number: str = call.data["number"]
    host = call.data.get(ATTR_HOST)

    entries = hass.config_entries.async_entries(DOMAIN)
    welcome_msg = DEFAULT_WELCOME_MESSAGE
    if entries:
        welcome_msg = entries[0].options.get(CONF_WELCOME_MESSAGE, DEFAULT_WELCOME_MESSAGE)

    try:
        lte_entry = get_netgear_lte_entry(hass, host)
        modem = ModemConnection(lte_entry.runtime_data.modem)
        await modem.send_sms(number, welcome_msg)
        LOGGER.info("Sent welcome message to %s", number)
    except NetgearLTECoreMissingError as ex:
        raise ServiceValidationError(str(ex), translation_domain=DOMAIN) from ex
    except (EternalEgyptVersionError, ModemCommunicationError) as ex:
        raise ServiceValidationError(f"Send error: {ex}", translation_domain=DOMAIN) from ex
    except Exception as ex:
        LOGGER.exception("Unexpected error in send_welcome service")
        raise ServiceValidationError(f"Unexpected error: {type(ex).__name__}", translation_domain=DOMAIN) from ex


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register all services for Netgear LTE SMS Manager."""
    service_handlers = {
        SERVICE_LIST_INBOX: (_service_list_inbox, LIST_INBOX_SCHEMA),
        SERVICE_DELETE_SMS: (_service_delete_sms, DELETE_SMS_SCHEMA),
        SERVICE_CLEANUP_INBOX: (_service_cleanup_inbox, CLEANUP_INBOX_SCHEMA),
        SERVICE_GET_INBOX_JSON: (_service_get_inbox_json, GET_INBOX_JSON_SCHEMA),
        SERVICE_ADD_CONTACT: (_service_add_contact, ADD_CONTACT_SCHEMA),
        SERVICE_UPDATE_CONTACT: (_service_update_contact, UPDATE_CONTACT_SCHEMA),
        SERVICE_REMOVE_CONTACT: (_service_remove_contact, REMOVE_CONTACT_SCHEMA),
        SERVICE_SEND_WELCOME: (_service_send_welcome, SEND_WELCOME_SCHEMA),
    }

    for service_name, (handler, schema) in service_handlers.items():
        hass.services.async_register(DOMAIN, service_name, handler, schema=schema)
        LOGGER.info("Registered service: %s", service_name)
