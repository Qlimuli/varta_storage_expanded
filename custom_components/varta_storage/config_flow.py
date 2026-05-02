"""Config flow for VARTA Storage integration."""

from __future__ import annotations

from typing import Any

from vartastorage import vartastorage
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DEFAULT_SCAN_INTERVAL_CGI,
    DEFAULT_SCAN_INTERVAL_MODBUS,
    DOMAIN,
    LOGGER,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=502): int,
        vol.Optional(
            "scan_interval_modbus", default=DEFAULT_SCAN_INTERVAL_MODBUS
        ): int,
        vol.Required("cgi", default=True): bool,
        vol.Optional("host_cgi", default=""): str,
        vol.Optional(CONF_USERNAME, default=""): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
        vol.Optional(
            "scan_interval_cgi", default=DEFAULT_SCAN_INTERVAL_CGI
        ): int,
    }
)


class VartaHub:
    """Provide methods for GUI configuration and connection testing."""

    def __init__(
        self,
        host: str,
        port: int,
        scan_interval_modbus: int,
        cgi: bool,
        host_cgi: str,
        username: str,
        password: str,
        scan_interval_cgi: int,
    ) -> None:
        """Initialize.

        Args:
            host: Host/IP for Modbus connection.
            port: Modbus port number.
            scan_interval_modbus: Polling interval for Modbus in seconds.
            cgi: Whether to enable CGI data fetching.
            host_cgi: Host/IP for CGI endpoint (empty string = use Modbus host).
            username: Username for CGI authentication.
            password: Password for CGI authentication.
            scan_interval_cgi: Polling interval for CGI in seconds.

        """
        self.host = host
        self.port = port
        self.serial = ""
        self.scan_interval_modbus = scan_interval_modbus
        self.cgi = cgi
        self.host_cgi = host_cgi
        self.username = username
        self.password = password
        self.scan_interval_cgi = scan_interval_cgi

    def test_connection(self) -> bool:
        """Test a connection to the VartaStorage device via Modbus."""
        try:
            varta = vartastorage.VartaStorage(
                self.host, self.port, False, self.username, self.password
            )
            self.serial = varta.modbus_client.get_serial()
            return True
        except (ValueError, ConnectionError, OSError) as exc:
            LOGGER.debug("Connection test failed: %s", exc)
            return False
        except Exception as exc:
            LOGGER.warning("Unexpected error during connection test: %s", exc)
            return False


async def validate_input(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    hub = VartaHub(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        scan_interval_modbus=data.get(
            "scan_interval_modbus", DEFAULT_SCAN_INTERVAL_MODBUS
        ),
        cgi=data.get("cgi", True),
        host_cgi=data.get("host_cgi", ""),
        username=data.get(CONF_USERNAME, ""),
        password=data.get(CONF_PASSWORD, ""),
        scan_interval_cgi=data.get(
            "scan_interval_cgi", DEFAULT_SCAN_INTERVAL_CGI
        ),
    )

    # PyPI package is not async, passing to the sync executor
    if not await hass.async_add_executor_job(hub.test_connection):
        raise CannotConnect

    return {
        "title": f"{data[CONF_HOST]} (S/N: {hub.serial})",
        "serial": hub.serial,
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for VARTA Storage."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors: dict[str, str] = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception as exc:
            LOGGER.warning("Unexpected exception during config flow: %s", exc)
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(info["serial"])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=info["title"], data=user_input
            )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for VARTA Storage."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        # Merge current data and options to get effective values
        current = dict(self._config_entry.data)
        current.update(self._config_entry.options)

        if user_input is not None:
            # Validate connection with new settings
            errors: dict[str, str] = {}
            try:
                await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception as exc:
                LOGGER.warning(
                    "Unexpected exception during options flow: %s", exc
                )
                errors["base"] = "unknown"
            else:
                # Update config entry data with new values
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=user_input,
                )
                # Return empty options - all data stored in entry.data
                return self.async_create_entry(
                    title=self._config_entry.title, data={}
                )

            # Show form again with errors
            return self.async_show_form(
                step_id="init",
                data_schema=self._build_schema(user_input),
                errors=errors,
            )

        return self.async_show_form(
            step_id="init",
            data_schema=self._build_schema(current),
        )

    def _build_schema(
        self, current: dict[str, Any]
    ) -> vol.Schema:
        """Build the options schema with current values as defaults."""
        return vol.Schema(
            {
                vol.Required(
                    CONF_HOST,
                    default=current.get(CONF_HOST, ""),
                ): str,
                vol.Required(
                    CONF_PORT,
                    default=current.get(CONF_PORT, 502),
                ): int,
                vol.Optional(
                    "scan_interval_modbus",
                    default=current.get(
                        "scan_interval_modbus", DEFAULT_SCAN_INTERVAL_MODBUS
                    ),
                ): int,
                vol.Required(
                    "cgi",
                    default=current.get("cgi", True),
                ): bool,
                vol.Optional(
                    "host_cgi",
                    default=current.get("host_cgi", ""),
                ): str,
                vol.Optional(
                    CONF_USERNAME,
                    default=current.get(CONF_USERNAME, ""),
                ): str,
                vol.Optional(
                    CONF_PASSWORD,
                    default=current.get(CONF_PASSWORD, ""),
                ): str,
                vol.Optional(
                    "scan_interval_cgi",
                    default=current.get(
                        "scan_interval_cgi", DEFAULT_SCAN_INTERVAL_CGI
                    ),
                ): int,
            }
        )
