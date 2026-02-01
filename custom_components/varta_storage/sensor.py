"""Sensor platform of the VARTA Storage integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    INTEGRATION_SCAN_INTERVAL,
    LOGGER,
    SENSORS_CALCULATED,
    SENSORS_CGI,
    SENSORS_MODBUS,
    SENSORS_RIEMANN,
    SensorCategory,
    VartaSensorEntityDescription,
    get_error_text,
    get_state_text,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Initialize the integration."""
    coordinators = hass.data[DOMAIN][entry.entry_id]
    modbus_coordinator = coordinators["modbus"]
    cgi_coordinator = coordinators.get("cgi")

    entities: list[SensorEntity] = []

    # Standard Modbus sensors
    entities.extend(
        VartaStorageEntity(modbus_coordinator, description=description)
        for description in SENSORS_MODBUS
    )

    # CGI sensors (if CGI is enabled)
    if entry.data.get("cgi") and cgi_coordinator:
        entities.extend(
            VartaStorageEntity(cgi_coordinator, description=description)
            for description in SENSORS_CGI
        )

    # Riemann integration sensors (power -> energy conversion)
    entities.extend(
        VartaRiemannSensor(
            hass=hass,
            coordinator=modbus_coordinator,
            description=description,
            entry=entry,
        )
        for description in SENSORS_RIEMANN
    )

    # Calculated sensors (derived metrics)
    entities.extend(
        VartaCalculatedSensor(
            hass=hass,
            coordinator=modbus_coordinator,
            cgi_coordinator=cgi_coordinator,
            description=description,
            entry=entry,
        )
        for description in SENSORS_CALCULATED
    )

    async_add_entities(entities)


class VartaStorageEntity(CoordinatorEntity, SensorEntity):
    """Standard VARTA sensor entity using CoordinatorEntity.

    The CoordinatorEntity class provides:
    should_poll, async_update, async_added_to_hass, available
    """

    entity_description: VartaSensorEntityDescription

    def __init__(self, coordinator, description: VartaSensorEntityDescription):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)

        self._attr_device_info = DeviceInfo(
            configuration_url=f"http://{coordinator.config_entry.data['host']}",
            identifiers={(DOMAIN, str(coordinator.config_entry.unique_id))},
            manufacturer="VARTA",
            name="VARTA Battery",
        )

        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}-{self.entity_description.key}"
        )

        # Set suggested display precision if specified
        if description.suggested_display_precision is not None:
            self._attr_suggested_display_precision = (
                description.suggested_display_precision
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.entity_description.source_key is None:
            raise ValueError(
                "Invalid entity configuration: source_key is not set in varta entity description."
            )

        value = self.coordinator.data.get(self.entity_description.source_key)

        # Handle special cases for apparent power (convert to VA)
        if self.entity_description.key == "powerApparent" and value is not None:
            # The library returns apparent power - ensure it's positive
            value = abs(value) if value is not None else None

        # Convert state code to human-readable text
        elif self.entity_description.key == "stateTextDerived" and value is not None:
            try:
                value = get_state_text(int(value))
            except (ValueError, TypeError):
                value = f"Unknown State ({value})"

        # Convert error code to human-readable text
        elif self.entity_description.key == "errorText" and value is not None:
            try:
                value = get_error_text(int(value))
            except (ValueError, TypeError):
                value = f"Unknown Error ({value})"

        self._attr_native_value = value
        self.async_write_ha_state()


class VartaRiemannSensor(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Riemann sum integration sensor for converting power (W) to energy (kWh).

    Uses the trapezoidal method for better accuracy.
    """

    entity_description: VartaSensorEntityDescription

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator,
        description: VartaSensorEntityDescription,
        entry: ConfigEntry,
    ):
        """Initialize the Riemann integration sensor."""
        super().__init__(coordinator)

        self._hass = hass
        self._entry = entry
        self.entity_description = description

        self._attr_device_info = DeviceInfo(
            configuration_url=f"http://{coordinator.config_entry.data['host']}",
            identifiers={(DOMAIN, str(coordinator.config_entry.unique_id))},
            manufacturer="VARTA",
            name="VARTA Battery",
        )

        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}-{self.entity_description.key}"
        )

        if description.suggested_display_precision is not None:
            self._attr_suggested_display_precision = (
                description.suggested_display_precision
            )

        # Integration state
        self._total_energy: float = 0.0
        self._last_power: float | None = None
        self._last_update: datetime | None = None
        self._unsub_interval: Any = None

    async def async_added_to_hass(self) -> None:
        """Restore state and set up periodic updates."""
        await super().async_added_to_hass()

        # Restore previous state
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._total_energy = float(last_state.state)
            except (ValueError, TypeError):
                self._total_energy = 0.0
                LOGGER.warning(
                    "Could not restore state for %s, starting from 0",
                    self.entity_id,
                )

        # Set up periodic integration calculation
        self._unsub_interval = async_track_time_interval(
            self._hass,
            self._async_integrate,
            timedelta(seconds=INTEGRATION_SCAN_INTERVAL),
        )

        # Initial integration
        await self._async_integrate(dt_util.utcnow())

    async def async_will_remove_from_hass(self) -> None:
        """Clean up on removal."""
        if self._unsub_interval:
            self._unsub_interval()
            self._unsub_interval = None

    async def _async_integrate(self, now: datetime) -> None:
        """Perform Riemann sum integration."""
        if self.coordinator.data is None:
            return

        source_key = self.entity_description.source_key
        if source_key is None:
            return

        current_power = self.coordinator.data.get(source_key)

        if current_power is None:
            return

        # Ensure power is positive for accumulation
        current_power = abs(float(current_power))

        current_time = dt_util.utcnow()

        if self._last_power is not None and self._last_update is not None:
            # Calculate time delta in hours
            time_delta = (current_time - self._last_update).total_seconds() / 3600.0

            if time_delta > 0 and time_delta < 1:  # Sanity check (max 1 hour gap)
                # Trapezoidal integration: average of current and last power
                avg_power = (current_power + self._last_power) / 2.0

                # Convert W*h to kWh
                energy_increment = (avg_power * time_delta) / 1000.0

                self._total_energy += energy_increment

        # Store current values for next iteration
        self._last_power = current_power
        self._last_update = current_time

        # Update sensor state
        self._attr_native_value = round(self._total_energy, 6)
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator updates (we use our own integration timing)."""
        # Don't update on coordinator updates - we use our own timing
        pass

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return round(self._total_energy, 6) if self._total_energy else 0.0


class VartaCalculatedSensor(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Calculated sensor for derived metrics."""

    entity_description: VartaSensorEntityDescription

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator,
        cgi_coordinator,
        description: VartaSensorEntityDescription,
        entry: ConfigEntry,
    ):
        """Initialize the calculated sensor."""
        super().__init__(coordinator)

        self._hass = hass
        self._entry = entry
        self._cgi_coordinator = cgi_coordinator
        self.entity_description = description

        self._attr_device_info = DeviceInfo(
            configuration_url=f"http://{coordinator.config_entry.data['host']}",
            identifiers={(DOMAIN, str(coordinator.config_entry.unique_id))},
            manufacturer="VARTA",
            name="VARTA Battery",
        )

        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}-{self.entity_description.key}"
        )

        if description.suggested_display_precision is not None:
            self._attr_suggested_display_precision = (
                description.suggested_display_precision
            )

        # Daily tracking state
        self._daily_import: float = 0.0
        self._daily_export: float = 0.0
        self._last_import_total: float | None = None
        self._last_export_total: float | None = None
        self._last_reset_date: str | None = None
        self._unsub_interval: Any = None

    async def async_added_to_hass(self) -> None:
        """Restore state and set up periodic updates."""
        await super().async_added_to_hass()

        # Restore previous state for daily sensors
        if self.entity_description.key in ("dailyNetGridImport", "dailyNetGridExport"):
            if (last_state := await self.async_get_last_state()) is not None:
                try:
                    self._attr_native_value = float(last_state.state)
                    if last_state.attributes:
                        self._last_reset_date = last_state.attributes.get(
                            "last_reset_date"
                        )
                except (ValueError, TypeError):
                    pass

        # Set up periodic calculation
        self._unsub_interval = async_track_time_interval(
            self._hass,
            self._async_calculate,
            timedelta(seconds=INTEGRATION_SCAN_INTERVAL),
        )

        # Initial calculation
        await self._async_calculate(dt_util.utcnow())

    async def async_will_remove_from_hass(self) -> None:
        """Clean up on removal."""
        if self._unsub_interval:
            self._unsub_interval()
            self._unsub_interval = None

    async def _async_calculate(self, now: datetime) -> None:
        """Calculate the derived value."""
        if self.coordinator.data is None:
            return

        modbus_data = self.coordinator.data
        cgi_data = self._cgi_coordinator.data if self._cgi_coordinator else {}

        key = self.entity_description.key
        value = None

        try:
            if key == "dailyNetGridImport":
                value = self._calculate_daily_net_import(cgi_data)
            elif key == "dailyNetGridExport":
                value = self._calculate_daily_net_export(cgi_data)
            elif key == "batteryEfficiency":
                value = self._calculate_battery_efficiency(cgi_data)
            elif key == "selfSufficiencyRate":
                value = self._calculate_self_sufficiency(modbus_data, cgi_data)
            elif key == "selfConsumptionRate":
                value = self._calculate_self_consumption(modbus_data, cgi_data)
            elif key == "availableEnergy":
                value = self._calculate_available_energy(modbus_data)
            elif key == "timeToEmpty":
                value = self._calculate_time_to_empty(modbus_data)
            elif key == "timeToFull":
                value = self._calculate_time_to_full(modbus_data)
            elif key == "totalPowerFlow":
                value = self._calculate_total_power_flow(modbus_data)

        except (KeyError, TypeError, ZeroDivisionError) as e:
            LOGGER.debug("Error calculating %s: %s", key, e)
            value = None

        self._attr_native_value = value
        self.async_write_ha_state()

    def _calculate_daily_net_import(self, cgi_data: dict) -> float | None:
        """Calculate daily net grid import (consumption from grid)."""
        today = dt_util.now().date().isoformat()

        # Reset at midnight
        if self._last_reset_date != today:
            self._daily_import = 0.0
            self._last_import_total = None
            self._last_reset_date = today

        current_total = cgi_data.get("total_grid_ac_dc")  # Energy from grid
        if current_total is None:
            return self._daily_import

        if self._last_import_total is not None:
            delta = current_total - self._last_import_total
            if delta > 0:
                self._daily_import += delta

        self._last_import_total = current_total
        return round(self._daily_import, 3)

    def _calculate_daily_net_export(self, cgi_data: dict) -> float | None:
        """Calculate daily net grid export (feed-in to grid)."""
        today = dt_util.now().date().isoformat()

        # Reset at midnight
        if self._last_reset_date != today:
            self._daily_export = 0.0
            self._last_export_total = None
            self._last_reset_date = today

        current_total = cgi_data.get("total_grid_dc_ac")  # Energy to grid
        if current_total is None:
            return self._daily_export

        if self._last_export_total is not None:
            delta = current_total - self._last_export_total
            if delta > 0:
                self._daily_export += delta

        self._last_export_total = current_total
        return round(self._daily_export, 3)

    def _calculate_battery_efficiency(self, cgi_data: dict) -> float | None:
        """Calculate battery round-trip efficiency.

        Efficiency = (Energy Discharged / Energy Charged) * 100
        """
        charged = cgi_data.get("total_inverter_ac_dc")
        discharged = cgi_data.get("total_inverter_dc_ac")

        if charged is None or discharged is None or charged == 0:
            return None

        efficiency = (discharged / charged) * 100
        return min(efficiency, 100.0)  # Cap at 100%

    def _calculate_self_sufficiency(
        self, modbus_data: dict, cgi_data: dict
    ) -> float | None:
        """Calculate self-sufficiency rate (Autarkiequote).

        Self-sufficiency = (1 - Grid Import / Total Consumption) * 100
        Where Total Consumption = Grid Import + Battery Discharge + Direct PV Use
        Simplified: (Total Consumption - Grid Import) / Total Consumption * 100
        """
        grid_import = cgi_data.get("total_grid_ac_dc", 0)
        battery_discharge = cgi_data.get("total_inverter_dc_ac", 0)

        if grid_import is None or battery_discharge is None:
            return None

        total_consumption = grid_import + battery_discharge
        if total_consumption == 0:
            return 100.0  # No consumption = 100% self-sufficient

        self_consumed = battery_discharge
        rate = (self_consumed / total_consumption) * 100
        return min(max(rate, 0.0), 100.0)

    def _calculate_self_consumption(
        self, modbus_data: dict, cgi_data: dict
    ) -> float | None:
        """Calculate self-consumption rate (Eigenverbrauchsquote).

        Self-consumption = (1 - Grid Export / Total Generation) * 100
        """
        grid_export = cgi_data.get("total_grid_dc_ac", 0)
        battery_charge = cgi_data.get("total_inverter_ac_dc", 0)

        if grid_export is None or battery_charge is None:
            return None

        total_generation = grid_export + battery_charge
        if total_generation == 0:
            return 100.0  # No generation means 100% self-consumption

        self_consumed = total_generation - grid_export
        rate = (self_consumed / total_generation) * 100
        return min(max(rate, 0.0), 100.0)

    def _calculate_available_energy(self, modbus_data: dict) -> float | None:
        """Calculate available energy in battery (Wh).

        Available Energy = SoC (%) * Installed Capacity (Wh) / 100
        """
        soc = modbus_data.get("soc")
        capacity = modbus_data.get("installed_capacity")

        if soc is None or capacity is None:
            return None

        # Capacity is in W (actually Wh for storage)
        return (soc * capacity) / 100

    def _calculate_time_to_empty(self, modbus_data: dict) -> float | None:
        """Calculate estimated time to empty (minutes).

        Time = Available Energy (Wh) / Discharge Power (W) * 60
        """
        available = self._calculate_available_energy(modbus_data)
        discharge_power = modbus_data.get("discharge_power", 0)

        if available is None or discharge_power is None or discharge_power <= 0:
            return None

        # Time in minutes
        return (available / discharge_power) * 60

    def _calculate_time_to_full(self, modbus_data: dict) -> float | None:
        """Calculate estimated time to full (minutes).

        Time = (Capacity - Available Energy) / Charge Power * 60
        """
        soc = modbus_data.get("soc")
        capacity = modbus_data.get("installed_capacity")
        charge_power = modbus_data.get("charge_power", 0)

        if soc is None or capacity is None or charge_power is None or charge_power <= 0:
            return None

        remaining_capacity = capacity * (100 - soc) / 100

        # Time in minutes
        return (remaining_capacity / charge_power) * 60

    def _calculate_total_power_flow(self, modbus_data: dict) -> float | None:
        """Calculate total absolute power flow (W)."""
        charge = abs(modbus_data.get("charge_power", 0) or 0)
        discharge = abs(modbus_data.get("discharge_power", 0) or 0)

        return charge + discharge

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes for daily sensors."""
        if self.entity_description.key in ("dailyNetGridImport", "dailyNetGridExport"):
            return {"last_reset_date": self._last_reset_date}
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator updates (we use our own calculation timing)."""
        # Don't update on coordinator updates - we use our own timing
        pass
