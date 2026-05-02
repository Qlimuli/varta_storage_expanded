"""Sensor platform of the VARTA Storage integration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DOMAIN,
    LOGGER,
    SENSORS_CALCULATED,
    SENSORS_CGI,
    SENSORS_MODBUS,
    SENSORS_RIEMANN,
    VartaSensorEntityDescription,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up VARTA Storage sensor entities."""
    coordinators = hass.data[DOMAIN][entry.entry_id]
    modbus_coordinator: DataUpdateCoordinator = coordinators["modbus"]
    cgi_coordinator: DataUpdateCoordinator | None = coordinators.get("cgi")

    entities: list[SensorEntity] = []

    # --- Modbus Sensors ---
    for description in SENSORS_MODBUS:
        entities.append(
            VartaStorageEntity(
                coordinator=modbus_coordinator,
                description=description,
            )
        )

    # --- CGI Sensors (only if CGI is enabled and coordinator exists) ---
    if entry.data.get("cgi") and cgi_coordinator is not None:
        for description in SENSORS_CGI:
            entities.append(
                VartaStorageEntity(
                    coordinator=cgi_coordinator,
                    description=description,
                )
            )

    # --- Riemann Integral Sensors (Power -> Energy via time integration) ---
    for description in SENSORS_RIEMANN:
        entities.append(
            VartaRiemannEntity(
                coordinator=modbus_coordinator,
                description=description,
            )
        )

    # --- Calculated Sensors (derived from other sensor data) ---
    for description in SENSORS_CALCULATED:
        entities.append(
            VartaCalculatedEntity(
                modbus_coordinator=modbus_coordinator,
                cgi_coordinator=cgi_coordinator,
                description=description,
            )
        )

    async_add_entities(entities)


class VartaStorageEntity(CoordinatorEntity, SensorEntity):
    """Standard VARTA sensor entity using a single coordinator.

    The CoordinatorEntity class provides:
        should_poll
        async_update
        async_added_to_hass
        available
    """

    entity_description: VartaSensorEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: VartaSensorEntityDescription,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator)

        self._attr_device_info = DeviceInfo(
            configuration_url=f"http://{coordinator.config_entry.data['host']}",
            identifiers={(DOMAIN, str(coordinator.config_entry.unique_id))},
            manufacturer="VARTA",
            name="VARTA Battery",
        )

        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}-{description.key}"
        )

        if description.suggested_display_precision is not None:
            self._attr_suggested_display_precision = (
                description.suggested_display_precision
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.entity_description.source_key is None:
            LOGGER.error(
                "Invalid entity configuration: source_key is not set for %s",
                self.entity_description.key,
            )
            return

        if self.coordinator.data is not None:
            self._attr_native_value = self.coordinator.data.get(
                self.entity_description.source_key
            )
        else:
            self._attr_native_value = None

        self.async_write_ha_state()


class VartaRiemannEntity(CoordinatorEntity, SensorEntity):
    """VARTA Riemann integral sensor: converts power (W) to energy (kWh) over time.

    Uses trapezoidal integration to calculate cumulative energy from power readings.
    """

    entity_description: VartaSensorEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: VartaSensorEntityDescription,
    ) -> None:
        """Initialize the Riemann integration sensor."""
        super().__init__(coordinator)

        self._attr_device_info = DeviceInfo(
            configuration_url=f"http://{coordinator.config_entry.data['host']}",
            identifiers={(DOMAIN, str(coordinator.config_entry.unique_id))},
            manufacturer="VARTA",
            name="VARTA Battery",
        )

        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}-{description.key}"
        )

        if description.suggested_display_precision is not None:
            self._attr_suggested_display_precision = (
                description.suggested_display_precision
            )

        # Integration state
        self._accumulated_energy: float = 0.0
        self._last_power: float | None = None
        self._last_update: datetime | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data and integrate power over time."""
        if self.entity_description.source_key is None:
            LOGGER.error(
                "Invalid entity configuration: source_key is not set for %s",
                self.entity_description.key,
            )
            return

        if self.coordinator.data is None:
            self.async_write_ha_state()
            return

        current_power = self.coordinator.data.get(
            self.entity_description.source_key
        )
        now = datetime.now(timezone.utc)

        if current_power is not None and self._last_power is not None and self._last_update is not None:
            try:
                power_value = float(current_power)
                last_power_value = float(self._last_power)

                # Only integrate positive power values (energy produced/consumed)
                power_value = max(0.0, power_value)
                last_power_value = max(0.0, last_power_value)

                # Time delta in hours
                dt_hours = (now - self._last_update).total_seconds() / 3600.0

                # Sanity check: skip if time delta is unreasonably large (> 1 hour)
                if 0 < dt_hours <= 1.0:
                    # Trapezoidal integration: average power * time = energy
                    avg_power = (power_value + last_power_value) / 2.0
                    energy_kwh = (avg_power * dt_hours) / 1000.0  # W*h -> kWh
                    self._accumulated_energy += energy_kwh
            except (TypeError, ValueError) as exc:
                LOGGER.debug(
                    "Could not integrate power for %s: %s",
                    self.entity_description.key,
                    exc,
                )

        # Update tracking state
        if current_power is not None:
            self._last_power = current_power
            self._last_update = now

        self._attr_native_value = round(self._accumulated_energy, 6)
        self.async_write_ha_state()


class VartaCalculatedEntity(SensorEntity):
    """VARTA calculated sensor: derives values from Modbus and/or CGI data.

    These sensors compute metrics like efficiency, self-sufficiency,
    available energy, and time estimates.
    """

    entity_description: VartaSensorEntityDescription

    def __init__(
        self,
        modbus_coordinator: DataUpdateCoordinator,
        cgi_coordinator: DataUpdateCoordinator | None,
        description: VartaSensorEntityDescription,
    ) -> None:
        """Initialize the calculated sensor."""
        self._modbus_coordinator = modbus_coordinator
        self._cgi_coordinator = cgi_coordinator

        self._attr_device_info = DeviceInfo(
            configuration_url=f"http://{modbus_coordinator.config_entry.data['host']}",
            identifiers={
                (DOMAIN, str(modbus_coordinator.config_entry.unique_id))
            },
            manufacturer="VARTA",
            name="VARTA Battery",
        )

        self.entity_description = description
        self._attr_unique_id = (
            f"{modbus_coordinator.config_entry.unique_id}-{description.key}"
        )

        if description.suggested_display_precision is not None:
            self._attr_suggested_display_precision = (
                description.suggested_display_precision
            )

        # Daily tracking for net grid import/export
        self._daily_grid_import: float = 0.0
        self._daily_grid_export: float = 0.0
        self._last_day: int | None = None

    @property
    def should_poll(self) -> bool:
        """Return True because calculated sensors need periodic updates."""
        return False

    @property
    def available(self) -> bool:
        """Return True if the underlying coordinator(s) have data."""
        if self._modbus_coordinator.data is None:
            return False
        return True

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added to hass."""
        self.async_on_remove(
            self._modbus_coordinator.async_add_listener(
                self._handle_modbus_update
            )
        )
        if self._cgi_coordinator is not None:
            self.async_on_remove(
                self._cgi_coordinator.async_add_listener(
                    self._handle_cgi_update
                )
            )

    @callback
    def _handle_modbus_update(self) -> None:
        """Handle updated Modbus data and recalculate."""
        self._recalculate()

    @callback
    def _handle_cgi_update(self) -> None:
        """Handle updated CGI data and recalculate."""
        self._recalculate()

    def _get_modbus_value(self, key: str) -> float | None:
        """Safely get a float value from Modbus coordinator data."""
        if self._modbus_coordinator.data is None:
            return None
        val = self._modbus_coordinator.data.get(key)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _get_cgi_value(self, key: str) -> float | None:
        """Safely get a float value from CGI coordinator data."""
        if self._cgi_coordinator is None or self._cgi_coordinator.data is None:
            return None
        val = self._cgi_coordinator.data.get(key)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    @callback
    def _recalculate(self) -> None:
        """Recalculate the derived sensor value."""
        key = self.entity_description.source_key

        if key == "battery_efficiency":
            self._attr_native_value = self._calc_battery_efficiency()
        elif key == "self_sufficiency_rate":
            self._attr_native_value = self._calc_self_sufficiency_rate()
        elif key == "self_consumption_rate":
            self._attr_native_value = self._calc_self_consumption_rate()
        elif key == "daily_net_grid_import":
            self._attr_native_value = self._calc_daily_net_grid_import()
        elif key == "daily_net_grid_export":
            self._attr_native_value = self._calc_daily_net_grid_export()
        elif key == "available_energy":
            self._attr_native_value = self._calc_available_energy()
        elif key == "time_to_empty":
            self._attr_native_value = self._calc_time_to_empty()
        elif key == "time_to_full":
            self._attr_native_value = self._calc_time_to_full()
        else:
            LOGGER.warning(
                "Unknown calculated sensor source_key: %s", key
            )
            self._attr_native_value = None

        self.async_write_ha_state()

    def _calc_battery_efficiency(self) -> float | None:
        """Calculate battery round-trip efficiency.

        Efficiency = (total_inverter_dc_ac / total_inverter_ac_dc) * 100
        Uses CGI data (total inverter energy charged vs discharged).
        """
        discharged = self._get_cgi_value("total_inverter_dc_ac")
        charged = self._get_cgi_value("total_inverter_ac_dc")

        if charged is None or discharged is None:
            return None
        if charged <= 0:
            return None

        efficiency = (discharged / charged) * 100.0
        return min(round(efficiency, 1), 100.0)

    def _calc_self_sufficiency_rate(self) -> float | None:
        """Calculate self-sufficiency rate.

        Self-sufficiency = (1 - grid_import / total_consumption) * 100
        Uses CGI totals if available.
        """
        grid_import = self._get_cgi_value("total_grid_ac_dc")
        grid_export = self._get_cgi_value("total_grid_dc_ac")
        inverter_discharged = self._get_cgi_value("total_inverter_dc_ac")

        if grid_import is None or grid_export is None or inverter_discharged is None:
            return None

        # Total consumption = grid_import + inverter_discharged - grid_export
        total_consumption = grid_import + inverter_discharged - grid_export
        if total_consumption <= 0:
            return None

        rate = (1.0 - (grid_import / total_consumption)) * 100.0
        return max(0.0, min(round(rate, 1), 100.0))

    def _calc_self_consumption_rate(self) -> float | None:
        """Calculate self-consumption rate.

        Self-consumption = (1 - grid_export / total_production) * 100
        """
        grid_export = self._get_cgi_value("total_grid_dc_ac")
        inverter_discharged = self._get_cgi_value("total_inverter_dc_ac")

        if grid_export is None or inverter_discharged is None:
            return None

        total_production = inverter_discharged
        if total_production <= 0:
            return None

        rate = (1.0 - (grid_export / total_production)) * 100.0
        return max(0.0, min(round(rate, 1), 100.0))

    def _calc_daily_net_grid_import(self) -> float | None:
        """Calculate daily net grid import (resets at midnight)."""
        grid_power = self._get_modbus_value("grid_power")
        if grid_power is None:
            return None

        today = datetime.now().day
        if self._last_day is not None and self._last_day != today:
            self._daily_grid_import = 0.0
            self._daily_grid_export = 0.0
        self._last_day = today

        # Positive grid_power = importing from grid
        if grid_power > 0:
            return round(self._daily_grid_import, 3)
        return round(self._daily_grid_import, 3)

    def _calc_daily_net_grid_export(self) -> float | None:
        """Calculate daily net grid export (resets at midnight)."""
        grid_power = self._get_modbus_value("grid_power")
        if grid_power is None:
            return None

        return round(self._daily_grid_export, 3)

    def _calc_available_energy(self) -> float | None:
        """Calculate available energy in the battery.

        Available Energy = (SoC / 100) * installed_capacity_kWh
        """
        soc = self._get_modbus_value("soc")
        capacity = self._get_modbus_value("installed_capacity")

        if soc is None or capacity is None:
            return None
        if capacity <= 0:
            return None

        # installed_capacity is in Wh, convert to kWh
        capacity_kwh = capacity / 1000.0
        available = (soc / 100.0) * capacity_kwh
        return round(available, 2)

    def _calc_time_to_empty(self) -> float | None:
        """Calculate estimated time until battery is empty.

        Time = available_energy_Wh / discharge_power_W (in hours)
        """
        soc = self._get_modbus_value("soc")
        capacity = self._get_modbus_value("installed_capacity")
        discharge_power = self._get_modbus_value("discharge_power")

        if soc is None or capacity is None or discharge_power is None:
            return None
        if discharge_power <= 0:
            return None
        if capacity <= 0:
            return None

        available_wh = (soc / 100.0) * capacity
        hours = available_wh / discharge_power
        return round(hours, 1)

    def _calc_time_to_full(self) -> float | None:
        """Calculate estimated time until battery is full.

        Time = remaining_capacity_Wh / charge_power_W (in hours)
        """
        soc = self._get_modbus_value("soc")
        capacity = self._get_modbus_value("installed_capacity")
        charge_power = self._get_modbus_value("charge_power")

        if soc is None or capacity is None or charge_power is None:
            return None
        if charge_power <= 0:
            return None
        if capacity <= 0:
            return None

        remaining_wh = ((100.0 - soc) / 100.0) * capacity
        hours = remaining_wh / charge_power
        return round(hours, 1)
