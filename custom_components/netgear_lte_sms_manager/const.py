"""Constants for the Netgear LTE SMS Manager integration."""

import logging
from typing import Final

DOMAIN: Final = "netgear_lte_sms_manager"
DOMAIN_NETGEAR_CORE: Final = "netgear_lte"

LOGGER = logging.getLogger(__package__)

# Service names
SERVICE_LIST_INBOX: Final = "list_inbox"
SERVICE_DELETE_SMS: Final = "delete_sms"
SERVICE_CLEANUP_INBOX: Final = "cleanup_inbox"
SERVICE_GET_INBOX_JSON: Final = "get_inbox_json"
SERVICE_ADD_CONTACT: Final = "add_contact"
SERVICE_UPDATE_CONTACT: Final = "update_contact"
SERVICE_REMOVE_CONTACT: Final = "remove_contact"
SERVICE_SEND_WELCOME: Final = "send_welcome"

# Event names
EVENT_SMS_INBOX_LISTED: Final = "netgear_lte_sms_manager_inbox_listed"
EVENT_CLEANUP_COMPLETE: Final = "netgear_lte_sms_manager_cleanup_complete"
EVENT_NEW_SMS: Final = "netgear_lte_sms_manager_new_sms"

# Attributes
ATTR_HOST: Final = "host"
ATTR_SMS_ID: Final = "sms_id"
ATTR_MESSAGES: Final = "messages"
ATTR_WHITELIST: Final = "whitelist"
ATTR_RETAIN_COUNT: Final = "retain_count"
ATTR_RETAIN_DAYS: Final = "retain_days"
ATTR_DRY_RUN: Final = "dry_run"
ATTR_COUNT_DELETED: Final = "count_deleted"
ATTR_TIMESTAMP: Final = "timestamp"

# Config/options keys
CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_AUTO_OPT_OUT: Final = "auto_opt_out"
CONF_WELCOME_MESSAGE: Final = "welcome_message"

# Defaults
DEFAULT_RETAIN_COUNT: Final = 24
DEFAULT_RETAIN_DAYS: Final = 0
DEFAULT_DRY_RUN: Final = True
DEFAULT_POLL_INTERVAL: Final = 300
DEFAULT_WELCOME_MESSAGE: Final = (
    "Welcome to Home Assistant! Reply to this number to issue a simple command "
    "e.g. 'Lock front door'. Reply 'help' for available commands."
)
