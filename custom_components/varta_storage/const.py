"""Constants for the VARTA Storage integration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import logging
from typing import Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)

DOMAIN = "varta_storage"
LOGGER = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL_MODBUS = 3
DEFAULT_SCAN_INTERVAL_CGI = 10

# Integration calculation interval (seconds)
INTEGRATION_SCAN_INTERVAL = 60


# ============================================================================
# VARTA State Code Mappings (from Modbus documentation)
# ============================================================================
VARTA_STATE_MAP: Final[dict[int, str]] = {
    0: "Busy (Beschaeftigt)",
    1: "Run (Betrieb)",
    2: "Charge (Laden)",
    3: "Discharge (Entladen)",
    4: "Standby",
    5: "Error (Fehler)",
    6: "Passive (Service)",
    7: "Islanding (Inselbetrieb)",
    8: "Grid Outage (Netzausfall)",
    9: "Self Test (Selbsttest)",
    10: "Update",
    11: "Maintenance (Wartung)",
}

# ============================================================================
# VARTA Error Code Mappings (from documentation)
# ============================================================================
VARTA_ERROR_MAP: Final[dict[int, str]] = {
    0: "No Error (Kein Fehler)",
    1: "General Error (Allgemeiner Fehler)",
    2: "Battery Error (Batteriefehler)",
    3: "Inverter Error (Wechselrichterfehler)",
    4: "Grid Error (Netzfehler)",
    5: "Communication Error (Kommunikationsfehler)",
    6: "Temperature Error (Temperaturfehler)",
    7: "Overcurrent (Ueberstrom)",
    8: "Overvoltage (Ueberspannung)",
    9: "Undervoltage (Unterspannung)",
    10: "Overtemperature (Uebertemperatur)",
    11: "Undertemperature (Untertemperatur)",
    12: "Isolation Error (Isolationsfehler)",
    13: "Cell Imbalance (Zellenungleichgewicht)",
    14: "BMS Error (BMS-Fehler)",
    15: "EMS Error (EMS-Fehler)",
    16: "ENS Error (ENS-Fehler)",
    17: "Fan Error (Luefterfehler)",
    18: "Fuse Error (Sicherungsfehler)",
    19: "Relay Error (Relaisfehler)",
    20: "Sensor Error (Sensorfehler)",
    # Add more as needed based on actual documentation
    255: "Unknown Error (Unbekannter Fehler)",
}


def get_state_text(state_code: int | None) -> str:
    """Convert state code to human-readable text."""
    if state_code is None:
        return "Unknown"
    return VARTA_STATE_MAP.get(state_code, f"Unknown State ({state_code})")


def get_error_text(error_code: int | None) -> str:
    """Convert error code to human-readable text."""
    if error_code is None:
        return "Unknown"
    if error_code == 0:
        return "No Error (Kein Fehler)"
    return VARTA_ERROR_MAP.get(error_code, f"Unknown Error ({error_code})")


class SensorCategory(StrEnum):
    """Sensor categories for grouping."""

    MODBUS = "modbus"
    CGI = "cgi"
    CALCULATED = "calculated"
    RIEMANN = "riemann"


@dataclass
class VartaSensorEntityDescription(SensorEntityDescription):
    """Class describing Varta Storage entities."""

    source_key: str | None = None
    category: SensorCategory = SensorCategory.MODBUS
    suggested_display_precision: int | None = None


# ============================================================================
# MODBUS SENSORS - Direct readings from Modbus registers
# ============================================================================
SENSORS_MODBUS: Final[tuple[VartaSensorEntityDescription, ...]] = (
    # Battery State
    VartaSensorEntityDescription(
        key="stateOfCharge",
        name="VARTA State of Charge",
        source_key="soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        category=SensorCategory.MODBUS,
        icon="mdi:battery",
    ),
    VartaSensorEntityDescription(
        key="state",
        name="VARTA State Code",
        source_key="state",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.MODBUS,
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="stateText",
        name="VARTA State (Library)",
        source_key="state_text",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.MODBUS,
        icon="mdi:information",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="errorCode",
        name="VARTA Error Code",
        source_key="error_code",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.MODBUS,
        icon="mdi:alert-circle-outline",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="errorText",
        name="VARTA Error",
        source_key="error_code",  # We'll convert this in the sensor
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.MODBUS,
        icon="mdi:alert-circle",
    ),
    VartaSensorEntityDescription(
        key="stateTextDerived",
        name="VARTA Status",
        source_key="state",  # We'll convert this in the sensor
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.MODBUS,
        icon="mdi:information",
    ),
    # Power Measurements
    VartaSensorEntityDescription(
        key="gridPower",
        name="VARTA Grid Power",
        source_key="grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        category=SensorCategory.MODBUS,
        icon="mdi:transmission-tower",
    ),
    VartaSensorEntityDescription(
        key="gridPowerToGrid",
        name="VARTA Power To Grid",
        source_key="to_grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        category=SensorCategory.MODBUS,
        icon="mdi:transmission-tower-export",
    ),
    VartaSensorEntityDescription(
        key="gridPowerFromGrid",
        name="VARTA Power From Grid",
        source_key="from_grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        category=SensorCategory.MODBUS,
        icon="mdi:transmission-tower-import",
    ),
    VartaSensorEntityDescription(
        key="powerActive",
        name="VARTA Active Power",
        source_key="active_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        category=SensorCategory.MODBUS,
        icon="mdi:flash",
    ),
    VartaSensorEntityDescription(
        key="powerApparent",
        name="VARTA Apparent Power",
        source_key="apparent_power",
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        category=SensorCategory.MODBUS,
        icon="mdi:flash-outline",
    ),
    VartaSensorEntityDescription(
        key="powerCharge",
        name="VARTA Charging Power",
        source_key="charge_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        category=SensorCategory.MODBUS,
        icon="mdi:battery-charging",
    ),
    VartaSensorEntityDescription(
        key="powerDischarge",
        name="VARTA Discharging Power",
        source_key="discharge_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        category=SensorCategory.MODBUS,
        icon="mdi:battery-minus",
    ),
    # Energy Totals (Modbus)
    VartaSensorEntityDescription(
        key="powerChargeTotal",
        name="VARTA Total Energy Charged",
        source_key="total_charged_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        category=SensorCategory.MODBUS,
        icon="mdi:battery-charging-high",
    ),
    # System Info
    VartaSensorEntityDescription(
        key="software_version_ems",
        name="VARTA Software Version (EMS)",
        source_key="software_version_ems",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.MODBUS,
        icon="mdi:chip",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="software_version_ens",
        name="VARTA Software Version (ENS)",
        source_key="software_version_ens",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.MODBUS,
        icon="mdi:chip",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="software_version_inverter",
        name="VARTA Software Version (Inverter)",
        source_key="software_version_inverter",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.MODBUS,
        icon="mdi:chip",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="number_modules",
        name="VARTA Installed Battery Modules",
        source_key="number_modules",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        category=SensorCategory.MODBUS,
        icon="mdi:battery-outline",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="installed_capacity",
        name="VARTA Installed Capacity",
        source_key="installed_capacity",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        category=SensorCategory.MODBUS,
        icon="mdi:battery-high",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="serial",
        name="VARTA Serial Number",
        source_key="serial",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.MODBUS,
        icon="mdi:identifier",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="table_version",
        name="VARTA Table Version",
        source_key="table_version",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.MODBUS,
        icon="mdi:table",
        entity_registry_enabled_default=False,
    ),
)

# ============================================================================
# CGI SENSORS - Data from CGI/XML endpoints
# ============================================================================
SENSORS_CGI: Final[tuple[VartaSensorEntityDescription, ...]] = (
    # Energy Totals (CGI)
    VartaSensorEntityDescription(
        key="cycleCounter",
        name="VARTA Charging Cycle Counter",
        source_key="total_charge_cycles",
        device_class=None,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=None,
        category=SensorCategory.CGI,
        icon="mdi:counter",
    ),
    VartaSensorEntityDescription(
        key="gridPowerToTotal",
        name="VARTA Total Energy To Grid",
        source_key="total_grid_dc_ac",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        category=SensorCategory.CGI,
        icon="mdi:transmission-tower-export",
    ),
    VartaSensorEntityDescription(
        key="gridPowerFromTotal",
        name="VARTA Total Energy From Grid",
        source_key="total_grid_ac_dc",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        category=SensorCategory.CGI,
        icon="mdi:transmission-tower-import",
    ),
    VartaSensorEntityDescription(
        key="inverterDischarged",
        name="VARTA Inverter Energy Discharged",
        source_key="total_inverter_dc_ac",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        category=SensorCategory.CGI,
        icon="mdi:battery-arrow-down",
    ),
    VartaSensorEntityDescription(
        key="inverterCharged",
        name="VARTA Inverter Energy Charged",
        source_key="total_inverter_ac_dc",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        category=SensorCategory.CGI,
        icon="mdi:battery-arrow-up",
    ),
    # Service/Maintenance
    VartaSensorEntityDescription(
        key="maintenanceFilterDueIn",
        name="VARTA Hours Until Filter Maintenance",
        source_key="hours_until_filter_maintenance",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.HOURS,
        category=SensorCategory.CGI,
        icon="mdi:air-filter",
    ),
    VartaSensorEntityDescription(
        key="fan",
        name="VARTA Fan Status",
        source_key="status_fan",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.CGI,
        icon="mdi:fan",
    ),
    VartaSensorEntityDescription(
        key="main",
        name="VARTA Main Status",
        source_key="status_main",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.CGI,
        icon="mdi:power",
    ),
    # Inverter/WR Data
    VartaSensorEntityDescription(
        key="nominalPower",
        name="VARTA Nominal Power",
        source_key="nominal_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        category=SensorCategory.CGI,
        icon="mdi:flash-outline",
    ),
    VartaSensorEntityDescription(
        key="fanSpeed",
        name="VARTA Fan Speed",
        source_key="fan_speed",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        category=SensorCategory.CGI,
        icon="mdi:fan",
    ),
    VartaSensorEntityDescription(
        key="frequencyGrid",
        name="VARTA Grid Frequency",
        source_key="frequency_grid",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        category=SensorCategory.CGI,
        icon="mdi:sine-wave",
        suggested_display_precision=2,
    ),
    VartaSensorEntityDescription(
        key="onlineStatus",
        name="VARTA Online Status",
        source_key="online_status",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.CGI,
        icon="mdi:lan-connect",
    ),
    # Voltage Measurements (Grid Connection - Verbund)
    VartaSensorEntityDescription(
        key="voltageL1",
        name="VARTA Voltage L1",
        source_key="u_verbund_l1",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        category=SensorCategory.CGI,
        icon="mdi:flash",
        suggested_display_precision=1,
    ),
    VartaSensorEntityDescription(
        key="voltageL2",
        name="VARTA Voltage L2",
        source_key="u_verbund_l2",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        category=SensorCategory.CGI,
        icon="mdi:flash",
        suggested_display_precision=1,
    ),
    VartaSensorEntityDescription(
        key="voltageL3",
        name="VARTA Voltage L3",
        source_key="u_verbund_l3",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        category=SensorCategory.CGI,
        icon="mdi:flash",
        suggested_display_precision=1,
    ),
    # Current Measurements (Grid Connection - Verbund)
    VartaSensorEntityDescription(
        key="currentL1",
        name="VARTA Current L1",
        source_key="i_verbund_l1",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        category=SensorCategory.CGI,
        icon="mdi:current-ac",
        suggested_display_precision=2,
    ),
    VartaSensorEntityDescription(
        key="currentL2",
        name="VARTA Current L2",
        source_key="i_verbund_l2",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        category=SensorCategory.CGI,
        icon="mdi:current-ac",
        suggested_display_precision=2,
    ),
    VartaSensorEntityDescription(
        key="currentL3",
        name="VARTA Current L3",
        source_key="i_verbund_l3",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        category=SensorCategory.CGI,
        icon="mdi:current-ac",
        suggested_display_precision=2,
    ),
    # Temperature Measurements
    VartaSensorEntityDescription(
        key="tempL1",
        name="VARTA Temperature L1",
        source_key="temp_l1",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        category=SensorCategory.CGI,
        icon="mdi:thermometer",
    ),
    VartaSensorEntityDescription(
        key="tempL2",
        name="VARTA Temperature L2",
        source_key="temp_l2",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        category=SensorCategory.CGI,
        icon="mdi:thermometer",
    ),
    VartaSensorEntityDescription(
        key="tempL3",
        name="VARTA Temperature L3",
        source_key="temp_l3",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        category=SensorCategory.CGI,
        icon="mdi:thermometer",
    ),
    VartaSensorEntityDescription(
        key="tempBoard",
        name="VARTA Board Temperature",
        source_key="temp_board",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        category=SensorCategory.CGI,
        icon="mdi:thermometer",
    ),
    # Island Mode Voltage (Backup)
    VartaSensorEntityDescription(
        key="voltageIslandL1",
        name="VARTA Island Voltage L1",
        source_key="u_insel_l1",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        category=SensorCategory.CGI,
        icon="mdi:flash-triangle",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="voltageIslandL2",
        name="VARTA Island Voltage L2",
        source_key="u_insel_l2",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        category=SensorCategory.CGI,
        icon="mdi:flash-triangle",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="voltageIslandL3",
        name="VARTA Island Voltage L3",
        source_key="u_insel_l3",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        category=SensorCategory.CGI,
        icon="mdi:flash-triangle",
        entity_registry_enabled_default=False,
    ),
    # Island Mode Current (Backup)
    VartaSensorEntityDescription(
        key="currentIslandL1",
        name="VARTA Island Current L1",
        source_key="i_insel_l1",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        category=SensorCategory.CGI,
        icon="mdi:current-ac",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="currentIslandL2",
        name="VARTA Island Current L2",
        source_key="i_insel_l2",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        category=SensorCategory.CGI,
        icon="mdi:current-ac",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="currentIslandL3",
        name="VARTA Island Current L3",
        source_key="i_insel_l3",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        category=SensorCategory.CGI,
        icon="mdi:current-ac",
        entity_registry_enabled_default=False,
    ),
    # Device Info (CGI)
    VartaSensorEntityDescription(
        key="deviceDescription",
        name="VARTA Device Description",
        source_key="device_description",
        device_class=None,
        state_class=None,
        native_unit_of_measurement=None,
        category=SensorCategory.CGI,
        icon="mdi:information",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="pEmsMax",
        name="VARTA EMS Max Power",
        source_key="p_ems_max",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        category=SensorCategory.CGI,
        icon="mdi:speedometer",
        entity_registry_enabled_default=False,
    ),
    VartaSensorEntityDescription(
        key="pEmsMaxDisc",
        name="VARTA EMS Max Discharge Power",
        source_key="p_ems_maxdisc",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        category=SensorCategory.CGI,
        icon="mdi:speedometer",
        entity_registry_enabled_default=False,
    ),
)

# ============================================================================
# RIEMANN INTEGRAL SENSORS - Power to Energy conversion (W -> kWh)
# These create energy sensors from power sensors using Riemann sum integration
# ============================================================================
SENSORS_RIEMANN: Final[tuple[VartaSensorEntityDescription, ...]] = (
    VartaSensorEntityDescription(
        key="energyToGrid",
        name="VARTA Energy To Grid (Integrated)",
        source_key="to_grid_power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        category=SensorCategory.RIEMANN,
        icon="mdi:transmission-tower-export",
        suggested_display_precision=3,
    ),
    VartaSensorEntityDescription(
        key="energyFromGrid",
        name="VARTA Energy From Grid (Integrated)",
        source_key="from_grid_power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        category=SensorCategory.RIEMANN,
        icon="mdi:transmission-tower-import",
        suggested_display_precision=3,
    ),
    VartaSensorEntityDescription(
        key="energyCharged",
        name="VARTA Energy Charged (Integrated)",
        source_key="charge_power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        category=SensorCategory.RIEMANN,
        icon="mdi:battery-charging",
        suggested_display_precision=3,
    ),
    VartaSensorEntityDescription(
        key="energyDischarged",
        name="VARTA Energy Discharged (Integrated)",
        source_key="discharge_power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        category=SensorCategory.RIEMANN,
        icon="mdi:battery-minus",
        suggested_display_precision=3,
    ),
)

# ============================================================================
# CALCULATED SENSORS - Derived metrics
# ============================================================================
SENSORS_CALCULATED: Final[tuple[VartaSensorEntityDescription, ...]] = (
    # Daily Net Grid Import/Export
    VartaSensorEntityDescription(
        key="dailyNetGridImport",
        name="VARTA Daily Net Grid Import",
        source_key="daily_net_grid_import",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        category=SensorCategory.CALCULATED,
        icon="mdi:home-import-outline",
        suggested_display_precision=2,
    ),
    VartaSensorEntityDescription(
        key="dailyNetGridExport",
        name="VARTA Daily Net Grid Export",
        source_key="daily_net_grid_export",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        category=SensorCategory.CALCULATED,
        icon="mdi:home-export-outline",
        suggested_display_precision=2,
    ),
    # Battery Efficiency
    VartaSensorEntityDescription(
        key="batteryEfficiency",
        name="VARTA Battery Round-Trip Efficiency",
        source_key="battery_efficiency",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        category=SensorCategory.CALCULATED,
        icon="mdi:percent",
        suggested_display_precision=1,
    ),
    # Self-Sufficiency Rate (Autarkiequote)
    VartaSensorEntityDescription(
        key="selfSufficiencyRate",
        name="VARTA Self-Sufficiency Rate",
        source_key="self_sufficiency_rate",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        category=SensorCategory.CALCULATED,
        icon="mdi:home-battery",
        suggested_display_precision=1,
    ),
    # Self-Consumption Rate (Eigenverbrauchsquote)
    VartaSensorEntityDescription(
        key="selfConsumptionRate",
        name="VARTA Self-Consumption Rate",
        source_key="self_consumption_rate",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        category=SensorCategory.CALCULATED,
        icon="mdi:home-lightning-bolt",
        suggested_display_precision=1,
    ),
    # Available Energy (based on SoC and capacity)
    VartaSensorEntityDescription(
        key="availableEnergy",
        name="VARTA Available Energy",
        source_key="available_energy",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        category=SensorCategory.CALCULATED,
        icon="mdi:battery-check",
        suggested_display_precision=0,
    ),
    # Time to Empty / Full (estimated)
    VartaSensorEntityDescription(
        key="timeToEmpty",
        name="VARTA Time to Empty",
        source_key="time_to_empty",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        category=SensorCategory.CALCULATED,
        icon="mdi:battery-arrow-down-outline",
        suggested_display_precision=0,
    ),
    VartaSensorEntityDescription(
        key="timeToFull",
        name="VARTA Time to Full",
        source_key="time_to_full",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        category=SensorCategory.CALCULATED,
        icon="mdi:battery-arrow-up-outline",
        suggested_display_precision=0,
    ),
    # Total Power (absolute power flow)
    VartaSensorEntityDescription(
        key="totalPowerFlow",
        name="VARTA Total Power Flow",
        source_key="total_power_flow",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        category=SensorCategory.CALCULATED,
        icon="mdi:flash-triangle-outline",
        suggested_display_precision=0,
    ),
)
