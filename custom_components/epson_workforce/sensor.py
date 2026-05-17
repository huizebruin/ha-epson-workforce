"""Sensor platform for Epson WorkForce/XP extended integration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import EpsonCoordinator
from .const import DOMAIN

# Ink colour display names
INK_COLOR_NAMES = {
    "BK": "Black",
    "K": "Black",
    "Y": "Yellow",
    "M": "Magenta",
    "C": "Cyan",
    "PBK": "Photo Black",
    "LC": "Light Cyan",
    "LM": "Light Magenta",
}


@dataclass(frozen=True)
class EpsonSensorDescription(SensorEntityDescription):
    data_key: str = ""
    entity_category: EntityCategory | None = None


# --------------------------------------------------------------------------- #
# Static sensor definitions (non-ink)                                         #
# --------------------------------------------------------------------------- #
SENSOR_DESCRIPTIONS: tuple[EpsonSensorDescription, ...] = (
    # Status
    EpsonSensorDescription(
        key="printer_status",
        data_key="printer_status",
        name="Printer Status",
        icon="mdi:printer",
    ),
    EpsonSensorDescription(
        key="scanner_status",
        data_key="scanner_status",
        name="Scanner Status",
        icon="mdi:scanner",
    ),
    # Network
    EpsonSensorDescription(
        key="wifi_ssid",
        data_key="wifi_ssid",
        name="Wi-Fi SSID",
        icon="mdi:wifi",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EpsonSensorDescription(
        key="wifi_signal",
        data_key="wifi_signal",
        name="Wi-Fi Signal",
        icon="mdi:wifi-strength-3",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EpsonSensorDescription(
        key="wifi_speed",
        data_key="wifi_speed",
        name="Wi-Fi Speed",
        icon="mdi:speedometer",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EpsonSensorDescription(
        key="wifi_channel",
        data_key="wifi_channel",
        name="Wi-Fi Channel",
        icon="mdi:access-point",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EpsonSensorDescription(
        key="wifi_mode",
        data_key="wifi_mode",
        name="Wi-Fi Mode",
        icon="mdi:wifi-settings",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EpsonSensorDescription(
        key="wifi_security",
        data_key="wifi_security",
        name="Wi-Fi Security",
        icon="mdi:shield-wifi",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EpsonSensorDescription(
        key="ip_address",
        data_key="ip_address",
        name="IP Address",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Page counters
    EpsonSensorDescription(
        key="total_pages",
        data_key="total_pages",
        name="Total Pages Printed",
        icon="mdi:file-document-multiple",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    EpsonSensorDescription(
        key="bw_pages",
        data_key="bw_pages",
        name="B&W Pages Printed",
        icon="mdi:file-document-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    EpsonSensorDescription(
        key="color_pages",
        data_key="color_pages",
        name="Color Pages Printed",
        icon="mdi:file-document",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    EpsonSensorDescription(
        key="bw_scans",
        data_key="bw_scans",
        name="B&W Scans",
        icon="mdi:scanner",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    EpsonSensorDescription(
        key="color_scans",
        data_key="color_scans",
        name="Color Scans",
        icon="mdi:scanner",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    EpsonSensorDescription(
        key="first_print_date",
        data_key="first_print_date",
        name="First Print Date",
        icon="mdi:calendar",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Device info / diagnostics
    EpsonSensorDescription(
        key="firmware",
        data_key="firmware",
        name="Firmware Version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EpsonSensorDescription(
        key="epson_connect_status",
        data_key="epson_connect_status",
        name="Epson Connect Status",
        icon="mdi:cloud-check",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from config entry."""
    coordinator: EpsonCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []

    # Static sensors
    for desc in SENSOR_DESCRIPTIONS:
        if coordinator.data and coordinator.data.get(desc.data_key) is not None:
            entities.append(EpsonStaticSensor(coordinator, entry, desc))

    # Ink level sensors (dynamic, one per detected cartridge)
    ink_levels: dict = coordinator.data.get("ink_levels", {}) if coordinator.data else {}
    for color_code, level in ink_levels.items():
        entities.append(EpsonInkSensor(coordinator, entry, color_code))

    async_add_entities(entities)


def _device_info(coordinator: EpsonCoordinator, entry: ConfigEntry) -> DeviceInfo:
    data = coordinator.data or {}
    return DeviceInfo(
        identifiers={(DOMAIN, data.get("serial_number") or entry.entry_id)},
        name=data.get("device_name") or f"Epson {coordinator.host}",
        manufacturer="Epson",
        model="XP-2150 Series",  # from title; could be made dynamic
        sw_version=data.get("firmware"),
        connections={("mac", data["mac_address"])} if data.get("mac_address") else set(),
    )


class EpsonStaticSensor(CoordinatorEntity[EpsonCoordinator], SensorEntity):
    """A sensor reading a single key from coordinator data."""

    entity_description: EpsonSensorDescription

    def __init__(
        self,
        coordinator: EpsonCoordinator,
        entry: ConfigEntry,
        description: EpsonSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(coordinator, entry)
        if description.entity_category:
            self._attr_entity_category = description.entity_category

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.data_key)


class EpsonInkSensor(CoordinatorEntity[EpsonCoordinator], SensorEntity):
    """Ink level sensor for one cartridge colour."""

    def __init__(
        self,
        coordinator: EpsonCoordinator,
        entry: ConfigEntry,
        color_code: str,
    ) -> None:
        super().__init__(coordinator)
        self._color_code = color_code
        color_name = INK_COLOR_NAMES.get(color_code, color_code)
        self._attr_name = f"Ink Level {color_name}"
        self._attr_unique_id = f"{entry.entry_id}_ink_{color_code.lower()}"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_icon = "mdi:water"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("ink_levels", {}).get(self._color_code)
