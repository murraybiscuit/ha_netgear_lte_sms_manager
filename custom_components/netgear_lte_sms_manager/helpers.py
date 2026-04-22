"""Helper functions for accessing the netgear_lte core component."""

from __future__ import annotations

import json
import re
import uuid

_OPT_OUT_RE = re.compile(
    r"(?:"
    r"(?:reply|text|send|SMS)\s+STOP\S*"
    r"|STOP2END"
    r"|Stop2[Ee]nd"
    r"|to\s+opt.?out"
    r"|to\s+unsubscribe"
    r"|to\s+stop\s+(?:messages|receiving|texts)"
    r")",
    re.IGNORECASE,
)

from .const import DOMAIN, DOMAIN_NETGEAR_CORE, LOGGER
from .models import NetgearLTECoreMissingError

HOST_KEY = "host"


def get_netgear_lte_entry(hass, host: str | None = None):
    """Get a netgear_lte config entry by host or return the first loaded entry."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN_NETGEAR_CORE)

    if not entries:
        raise NetgearLTECoreMissingError(
            "netgear_lte component is not configured. Please set up at least one Netgear LTE modem."
        )

    if host is None:
        if len(entries) == 1:
            LOGGER.debug("Using single configured Netgear LTE modem")
            return entries[0]
        raise NetgearLTECoreMissingError(
            f"Multiple Netgear LTE modems configured, host parameter is required. "
            f"Available hosts: {[e.data.get(HOST_KEY) for e in entries]}"
        )

    for entry in entries:
        if entry.data.get(HOST_KEY) == host:
            LOGGER.debug("Found netgear_lte entry for host %s", host)
            return entry

    raise NetgearLTECoreMissingError(
        f"No Netgear LTE modem found at {host}. "
        f"Available hosts: {[e.data.get(HOST_KEY) for e in entries]}"
    )


def get_all_netgear_modems(hass) -> dict[str, dict]:
    modems = {}
    for entry in hass.config_entries.async_loaded_entries(DOMAIN_NETGEAR_CORE):
        host = entry.data.get(HOST_KEY)
        if host and entry.runtime_data:
            modems[host] = {
                "title": entry.title,
                "host": host,
                "modem": entry.runtime_data.modem,
                "entry": entry,
            }
    LOGGER.debug("Found %d Netgear LTE modems", len(modems))
    return modems


def get_saved_options(hass) -> dict:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return {}
    return dict(entries[0].options or {})


def parse_whitelist_options(options: dict) -> dict:
    phone_numbers = set()
    contacts: dict[str, dict] = {}

    raw_nums = options.get("whitelist_numbers") or ""
    for line in (l.strip() for l in raw_nums.splitlines() if l.strip()):
        phone_numbers.add(line)

    raw_contacts = options.get("contacts") or ""
    if raw_contacts.strip().startswith("["):
        try:
            contacts_list = json.loads(raw_contacts)
            for c in contacts_list:
                cid = c.get("uuid") or str(uuid.uuid4())
                if c.get("name") and c.get("number"):
                    contacts[cid] = {"name": c["name"], "number": c["number"]}
        except (json.JSONDecodeError, TypeError):
            pass
    else:
        for line in (l.strip() for l in raw_contacts.splitlines() if l.strip()):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                name, number = parts[0], parts[1]
                if name and number:
                    cid = str(uuid.uuid4())
                    contacts[cid] = {"name": name, "number": number}

    return {"phone_numbers": phone_numbers, "contacts": contacts}


def is_opt_out_message(message: str) -> bool:
    return bool(_OPT_OUT_RE.search(message))


_HELP_RE = re.compile(r"^\s*help\s*$", re.IGNORECASE)


def is_help_message(text: str) -> bool:
    return bool(_HELP_RE.match(text))


def build_help_reply(commands: list[dict]) -> str:
    enabled = [c for c in commands if c.get("enabled", True) is not False]
    if not enabled:
        return "No commands configured."
    lines = ["Available commands:"]
    lines += [f"{c['name']}: {', '.join(c.get('keywords', []))}" for c in enabled]
    return "\n".join(lines)


def normalize_number(number: str) -> str:
    return re.sub(r"\D", "", number)


def load_contacts(options: dict) -> list[dict]:
    raw = options.get("contacts", "")
    if not raw:
        return []
    if raw.strip().startswith("["):
        try:
            contacts = json.loads(raw)
            return [c for c in contacts if c.get("name") and c.get("number")]
        except (json.JSONDecodeError, TypeError):
            return []
    contacts = []
    for line in (ln.strip() for ln in raw.splitlines() if ln.strip()):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0] and parts[1]:
            contacts.append({"uuid": str(uuid.uuid4()), "name": parts[0], "number": parts[1]})
    return contacts


def save_contacts(contacts: list[dict]) -> str:
    return json.dumps(contacts)


def load_commands(options: dict) -> list[dict]:
    """Load command definitions from options. Returns only valid (name + service + entity_id) entries."""
    raw = options.get("commands", "")
    if not raw:
        return []
    try:
        commands = json.loads(raw)
        return [
            c for c in commands
            if c.get("name") and c.get("service") and c.get("entity_id")
        ]
    except (json.JSONDecodeError, TypeError):
        return []


def save_commands(commands: list[dict]) -> str:
    return json.dumps(commands)


def keyword_match(text: str, commands: list[dict], include_disabled: bool = False) -> dict | None:
    """Return the first matching command whose keyword appears in text as whole words (case-insensitive).

    Skips disabled commands unless include_disabled is True.
    """
    normalized = re.sub(r"[^\w\s]", "", text.lower()).strip()
    for command in commands:
        if not include_disabled and command.get("enabled", True) is False:
            continue
        for kw in command.get("keywords", []):
            pattern = r"\b" + re.escape(kw.lower().strip()) + r"\b"
            if re.search(pattern, normalized):
                return command
    return None
