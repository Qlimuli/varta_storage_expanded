"""The VARTA Storage integration."""

from __future__ import annotations

from dataclasses import fields
from datetime import timedelta, datetime
from typing import Any

import async_timeout
from vartastorage import vartastorage

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER

PLATFORMS: list[Platform] = [Platform.SENSOR]


def flatten_dataclass(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Recursively flatten a dataclass into a flat dictionary.

    Handles nested dataclasses, dicts, and filters out None values.
    """
    flat_dict: dict[str, Any] = {}

    if hasattr(obj, "__dataclass_fields__"):
        for field in fields(obj):
            value = getattr(obj, field.name)
            if hasattr(value, "__dataclass_fields__"):
                # Recursively flatten nested dataclasses
                flat_dict.update(flatten_dataclass(value, prefix=""))
            elif value is not None:
                flat_dict[field.name] = value
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if hasattr(value, "__dataclass_fields__"):
                flat_dict.update(flatten_dataclass(value, prefix=""))
            elif value is not None:
                flat_dict[key] = value
    else:
        if obj is not None:
            flat_dict[str(obj)] = obj

    return flat_dict


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up VARTA Storage from a config entry."""

    # Validate required fields exist in config entry
    required_fields = [
        "scan_interval_modbus",
        "scan_interval_cgi",
        "host",
        "host_cgi",
        "port",
        "username",
        "password",
    ]
    missing_fields = [field for field in required_fields if field not in entry.data]
    if missing_fields:
        message = (
            "The new version of VARTA Storage integration requires reconfiguration "
            "due to newly introduced configuration options. "
            "Please [reconfigure the integration](/config/integrations/dashboard) "
            "in Home Assistant."
        )
        LOGGER.error(message)
        hass.async_create_task(
            hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "VARTA Storage Integration Requires Reconfiguration",
                    "message": message,
                    "notification_id": "varta_storage_reconfigure",
                },
                blocking=False,
            )
        )
        raise ConfigEntryNotReady(
            f"Missing required fields: {', '.join(missing_fields)}. "
            "Please reconfigure the integration."
        )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    scan_interval_modbus = timedelta(seconds=entry.data["scan_interval_modbus"])
    scan_interval_cgi = timedelta(seconds=entry.data["scan_interval_cgi"])

    # Determine effective CGI host: fall back to Modbus host if empty
    cgi_host = entry.data.get("host_cgi", "")
    if not cgi_host:
        cgi_host = entry.data["host"]

    # --- Modbus Coordinator ---

    async def async_update_modbus() -> dict[str, Any]:
        """Fetch data from Modbus interface."""

        def sync_update() -> dict[str, Any]:
            """Synchronous Modbus data fetch with retry."""
            last_exception: Exception | None = None

            for attempt in range(2):
                try:
                    v = vartastorage.VartaStorage(
                        entry.data["host"],
                        entry.data["port"],
                        False,
                        entry.data.get("username", ""),
                        entry.data.get("password", ""),
                    )
                    LOGGER.debug(
                        "Getting Modbus data (attempt %d)", attempt + 1
                    )
                    result = v.get_all_data_modbus()
                    return flatten_dataclass(result)
                except Exception as exc:
                    last_exception = exc
                    LOGGER.debug(
                        "Modbus attempt %d failed: %s", attempt + 1, exc
                    )

            LOGGER.warning(
                "Cannot retrieve Modbus data from VARTA device after 2 attempts: %s",
                last_exception,
            )
            raise UpdateFailed(
                "Cannot retrieve Modbus data from the VARTA device."
            ) from last_exception

        try:
            async with async_timeout.timeout(15):
                return await hass.async_add_executor_job(sync_update)
        except UpdateFailed:
            raise
        except TimeoutError as err:
            raise UpdateFailed(
                "Timeout communicating with Modbus interface"
            ) from err
        except Exception as err:
            raise UpdateFailed(
                f"Error communicating with Modbus API: {err}"
            ) from err

    modbus_coordinator = DataUpdateCoordinator(
        hass,
        LOGGER,
        name=f"{DOMAIN}_modbus_{entry.data['host']}",
        update_method=async_update_modbus,
        update_interval=scan_interval_modbus,
        config_entry=entry,
    )

    # --- CGI Coordinator (optional) ---

    cgi_coordinator = None

    if entry.data.get("cgi", False):

        async def async_update_cgi() -> dict[str, Any]:
            """Fetch data from CGI/XML interface."""

            def sync_update() -> dict[str, Any]:
                """Synchronous CGI data fetch with retry."""
                last_exception: Exception | None = None

                for attempt in range(2):
                    try:
                        v = vartastorage.VartaStorage(
                            cgi_host,
                            entry.data["port"],
                            True,
                            entry.data.get("username", ""),
                            entry.data.get("password", ""),
                        )
                        LOGGER.debug(
                            "Getting CGI data from %s (attempt %d)",
                            cgi_host,
                            attempt + 1,
                        )
                        result = v.get_all_data_cgi()
                        return flatten_dataclass(result)
                    except Exception as exc:
                        last_exception = exc
                        LOGGER.debug(
                            "CGI attempt %d failed: %s", attempt + 1, exc
                        )

                LOGGER.warning(
                    "Cannot retrieve CGI data from VARTA device after 2 attempts: %s",
                    last_exception,
                )
                raise UpdateFailed(
                    "Cannot retrieve CGI data from the VARTA device."
                ) from last_exception

            try:
                async with async_timeout.timeout(15):
                    return await hass.async_add_executor_job(sync_update)
            except UpdateFailed:
                raise
            except TimeoutError as err:
                raise UpdateFailed(
                    "Timeout communicating with CGI interface"
                ) from err
            except Exception as err:
                raise UpdateFailed(
                    f"Error communicating with CGI API: {err}"
                ) from err

        cgi_coordinator = DataUpdateCoordinator(
            hass,
            LOGGER,
            name=f"{DOMAIN}_cgi_{cgi_host}",
            update_method=async_update_cgi,
            update_interval=scan_interval_cgi,
            config_entry=entry,
        )

    # --- Initial Data Fetch ---

    await modbus_coordinator.async_config_entry_first_refresh()

    if cgi_coordinator is not None:
        try:
            await cgi_coordinator.async_config_entry_first_refresh()
        except ConfigEntryNotReady:
            LOGGER.warning(
                "CGI endpoint not available during setup. "
                "CGI sensors will become available when the endpoint responds."
            )
            # Don't fail the entire integration if CGI is not available
            # The coordinator will retry automatically

    # Store coordinators
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "modbus": modbus_coordinator,
        "cgi": cgi_coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

        # Clean up domain data if no more entries
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
