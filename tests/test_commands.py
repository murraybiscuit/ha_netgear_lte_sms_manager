"""TDD tests for SMS command data model and keyword matcher — Layer 1."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.netgear_lte_sms_manager.helpers import (
    keyword_match,
    load_commands,
    save_commands,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LOCK_CMD = {
    "uuid": "uuid-lock",
    "name": "lock front door",
    "keywords": ["lock front door", "lock door", "lock up", "lock"],
    "service": "lock.lock",
    "entity_id": "lock.front_door_lock",
    "service_data": {},
    "reply_ok": "Front door locked.",
    "reply_fail": "Failed to lock front door.",
}

UNLOCK_CMD = {
    "uuid": "uuid-unlock",
    "name": "unlock front door",
    "keywords": ["unlock front door", "unlock door", "unlock"],
    "service": "lock.unlock",
    "entity_id": "lock.front_door_lock",
    "service_data": {},
    "reply_ok": "Front door unlocked.",
    "reply_fail": "Failed to unlock front door.",
}

GARAGE_OPEN_CMD = {
    "uuid": "uuid-garage-open",
    "name": "open garage",
    "keywords": ["open garage", "garage open", "garage up"],
    "service": "cover.open_cover",
    "entity_id": "cover.garage_door",
    "service_data": {},
    "reply_ok": "Garage door opening.",
    "reply_fail": "Failed to open garage door.",
}

GARAGE_CLOSE_CMD = {
    "uuid": "uuid-garage-close",
    "name": "close garage",
    "keywords": ["close garage", "garage close", "garage down", "close the garage"],
    "service": "cover.close_cover",
    "entity_id": "cover.garage_door",
    "service_data": {},
    "reply_ok": "Garage door closing.",
    "reply_fail": "Failed to close garage door.",
}

ALL_COMMANDS = [UNLOCK_CMD, LOCK_CMD, GARAGE_OPEN_CMD, GARAGE_CLOSE_CMD]


# ---------------------------------------------------------------------------
# load_commands / save_commands
# ---------------------------------------------------------------------------

class TestLoadCommands:
    def test_empty_options(self) -> None:
        assert load_commands({}) == []

    def test_missing_key(self) -> None:
        assert load_commands({"contacts": "[]"}) == []

    def test_loads_valid_json(self) -> None:
        options = {"commands": save_commands([LOCK_CMD])}
        result = load_commands(options)
        assert len(result) == 1
        assert result[0]["name"] == "lock front door"
        assert result[0]["entity_id"] == "lock.front_door_lock"

    def test_filters_incomplete_commands(self) -> None:
        incomplete = [
            {"uuid": "x", "name": "no service"},      # missing service + entity_id
            {"uuid": "y", "service": "lock.lock"},     # missing name + entity_id
            LOCK_CMD,
        ]
        options = {"commands": json.dumps(incomplete)}
        result = load_commands(options)
        assert len(result) == 1
        assert result[0]["uuid"] == "uuid-lock"

    def test_round_trips(self) -> None:
        serialized = save_commands(ALL_COMMANDS)
        loaded = load_commands({"commands": serialized})
        assert len(loaded) == 4
        assert loaded[2]["service"] == "cover.open_cover"

    def test_malformed_json_returns_empty(self) -> None:
        assert load_commands({"commands": "not json {"}) == []


# ---------------------------------------------------------------------------
# keyword_match — exact and fuzzy cases
# ---------------------------------------------------------------------------

class TestKeywordMatch:
    def test_no_commands(self) -> None:
        assert keyword_match("lock the door", []) is None

    def test_exact_keyword(self) -> None:
        result = keyword_match("lock", ALL_COMMANDS)
        # unlock contains "unlock" not "lock" (lock is substring of unlock — ordering matters)
        # unlock is first in list, "lock" is not in unlock keywords → falls through to LOCK_CMD
        assert result is not None
        assert result["uuid"] == "uuid-lock"

    def test_multi_word_keyword(self) -> None:
        result = keyword_match("lock front door", ALL_COMMANDS)
        assert result["uuid"] == "uuid-lock"

    def test_case_insensitive(self) -> None:
        assert keyword_match("LOCK", ALL_COMMANDS)["uuid"] == "uuid-lock"
        assert keyword_match("Lock The Door", ALL_COMMANDS)["uuid"] == "uuid-lock"

    def test_keyword_in_sentence(self) -> None:
        result = keyword_match("hey can you lock up the house?", ALL_COMMANDS)
        assert result["uuid"] == "uuid-lock"

    def test_unlock_preferred_over_lock(self) -> None:
        # UNLOCK_CMD is first in list and has "unlock" keyword — should match before lock
        result = keyword_match("please unlock the front door", ALL_COMMANDS)
        assert result["uuid"] == "uuid-unlock"

    def test_garage_open(self) -> None:
        assert keyword_match("open garage", ALL_COMMANDS)["uuid"] == "uuid-garage-open"
        assert keyword_match("garage up", ALL_COMMANDS)["uuid"] == "uuid-garage-open"

    def test_garage_close(self) -> None:
        assert keyword_match("close the garage", ALL_COMMANDS)["uuid"] == "uuid-garage-close"
        assert keyword_match("garage down", ALL_COMMANDS)["uuid"] == "uuid-garage-close"

    def test_no_match(self) -> None:
        assert keyword_match("hello how are you", ALL_COMMANDS) is None
        assert keyword_match("status", ALL_COMMANDS) is None

    def test_empty_message(self) -> None:
        assert keyword_match("", ALL_COMMANDS) is None

    def test_punctuation_stripped(self) -> None:
        assert keyword_match("lock!", ALL_COMMANDS)["uuid"] == "uuid-lock"
        assert keyword_match("lock.", ALL_COMMANDS)["uuid"] == "uuid-lock"

    def test_most_specific_keyword_wins(self) -> None:
        # "open garage" is more specific than a hypothetical "open" keyword
        # Ensure multi-word match works alongside single-word in same command
        result = keyword_match("can you open garage please", ALL_COMMANDS)
        assert result["uuid"] == "uuid-garage-open"


# ---------------------------------------------------------------------------
# Command services — add / remove / update
# ---------------------------------------------------------------------------

class TestAddCommandService:
    @pytest.mark.asyncio
    async def test_add_command_persists(self, mock_hass: MagicMock) -> None:
        from custom_components.netgear_lte_sms_manager.services import (
            _service_add_command,
        )

        sms_entry = MagicMock()
        sms_entry.options = {}
        mock_hass.config_entries.async_entries.return_value = [sms_entry]

        call = MagicMock()
        call.hass = mock_hass
        call.data = {
            "name": "lock front door",
            "keywords": ["lock", "lock door"],
            "service": "lock.lock",
            "entity_id": "lock.front_door_lock",
            "service_data": {},
            "reply_ok": "Locked.",
            "reply_fail": "Failed.",
        }

        await _service_add_command(call)

        mock_hass.config_entries.async_update_entry.assert_called_once()
        updated_options = mock_hass.config_entries.async_update_entry.call_args[1]["options"]
        commands = load_commands(updated_options)
        assert len(commands) == 1
        assert commands[0]["name"] == "lock front door"
        assert commands[0]["service"] == "lock.lock"

    @pytest.mark.asyncio
    async def test_add_command_fires_event(self, mock_hass: MagicMock) -> None:
        from custom_components.netgear_lte_sms_manager.const import EVENT_COMMAND_ADDED
        from custom_components.netgear_lte_sms_manager.services import (
            _service_add_command,
        )

        sms_entry = MagicMock()
        sms_entry.options = {}
        mock_hass.config_entries.async_entries.return_value = [sms_entry]

        call = MagicMock()
        call.hass = mock_hass
        call.data = {
            "name": "lock front door",
            "keywords": ["lock"],
            "service": "lock.lock",
            "entity_id": "lock.front_door_lock",
            "service_data": {},
            "reply_ok": "Locked.",
            "reply_fail": "Failed.",
        }

        await _service_add_command(call)

        fired_events = [c[0][0] for c in mock_hass.bus.async_fire.call_args_list]
        assert EVENT_COMMAND_ADDED in fired_events

    @pytest.mark.asyncio
    async def test_add_command_no_config_entry(self, mock_hass: MagicMock) -> None:
        from custom_components.netgear_lte_sms_manager.services import (
            _service_add_command,
        )

        mock_hass.config_entries.async_entries.return_value = []

        call = MagicMock()
        call.hass = mock_hass
        call.data = {
            "name": "lock front door",
            "keywords": ["lock"],
            "service": "lock.lock",
            "entity_id": "lock.front_door_lock",
            "service_data": {},
            "reply_ok": "Locked.",
            "reply_fail": "Failed.",
        }

        with pytest.raises(Exception):
            await _service_add_command(call)


class TestRemoveCommandService:
    @pytest.mark.asyncio
    async def test_remove_existing_command(self, mock_hass: MagicMock) -> None:
        from custom_components.netgear_lte_sms_manager.services import (
            _service_remove_command,
        )

        sms_entry = MagicMock()
        sms_entry.options = {"commands": save_commands([LOCK_CMD, UNLOCK_CMD])}
        mock_hass.config_entries.async_entries.return_value = [sms_entry]

        call = MagicMock()
        call.hass = mock_hass
        call.data = {"command_id": "uuid-lock"}

        await _service_remove_command(call)

        updated_options = mock_hass.config_entries.async_update_entry.call_args[1]["options"]
        remaining = load_commands(updated_options)
        assert len(remaining) == 1
        assert remaining[0]["uuid"] == "uuid-unlock"

    @pytest.mark.asyncio
    async def test_remove_nonexistent_is_noop(self, mock_hass: MagicMock) -> None:
        from custom_components.netgear_lte_sms_manager.services import (
            _service_remove_command,
        )

        sms_entry = MagicMock()
        sms_entry.options = {"commands": save_commands([LOCK_CMD])}
        mock_hass.config_entries.async_entries.return_value = [sms_entry]

        call = MagicMock()
        call.hass = mock_hass
        call.data = {"command_id": "does-not-exist"}

        await _service_remove_command(call)

        mock_hass.config_entries.async_update_entry.assert_not_called()


class TestUpdateCommandService:
    @pytest.mark.asyncio
    async def test_update_command_fields(self, mock_hass: MagicMock) -> None:
        from custom_components.netgear_lte_sms_manager.services import (
            _service_update_command,
        )

        sms_entry = MagicMock()
        sms_entry.options = {"commands": save_commands([LOCK_CMD])}
        mock_hass.config_entries.async_entries.return_value = [sms_entry]

        call = MagicMock()
        call.hass = mock_hass
        call.data = {
            "command_id": "uuid-lock",
            "name": "deadbolt",
            "keywords": ["deadbolt", "bolt"],
            "service": "lock.lock",
            "entity_id": "lock.front_door_lock",
            "service_data": {},
            "reply_ok": "Bolted.",
            "reply_fail": "Bolt failed.",
        }

        await _service_update_command(call)

        updated_options = mock_hass.config_entries.async_update_entry.call_args[1]["options"]
        cmds = load_commands(updated_options)
        assert cmds[0]["name"] == "deadbolt"
        assert cmds[0]["keywords"] == ["deadbolt", "bolt"]
        assert cmds[0]["reply_ok"] == "Bolted."

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises(self, mock_hass: MagicMock) -> None:
        from custom_components.netgear_lte_sms_manager.services import (
            _service_update_command,
        )

        sms_entry = MagicMock()
        sms_entry.options = {"commands": save_commands([LOCK_CMD])}
        mock_hass.config_entries.async_entries.return_value = [sms_entry]

        call = MagicMock()
        call.hass = mock_hass
        call.data = {
            "command_id": "does-not-exist",
            "name": "x",
            "keywords": ["x"],
            "service": "lock.lock",
            "entity_id": "lock.front_door_lock",
            "service_data": {},
            "reply_ok": "ok",
            "reply_fail": "fail",
        }

        with pytest.raises(Exception):
            await _service_update_command(call)
