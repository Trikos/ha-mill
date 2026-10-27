"""Support for mill wifi-enabled home heaters."""

from datetime import datetime, timedelta
from typing import Any, override

from mill import Heater, MillDevice

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CLOUD, CONNECTION_TYPE
from .coordinator import MillConfigEntry, MillDataUpdateCoordinator
from .entity import MillBaseEntity

MODE_INDIVIDUAL = "control_individually"

# The cloud reports a new setting only after the heater has picked it up, which
# can take a few minutes. Until then, show what was last written.
PENDING_TIMEOUT = timedelta(minutes=10)

_pending: dict[tuple[str, str], tuple[float, datetime]] = {}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MillConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Mill Number."""
    if entry.data.get(CONNECTION_TYPE) == CLOUD:
        mill_data_coordinator = entry.runtime_data

        heaters = [
            mill_device
            for mill_device in mill_data_coordinator.data.values()
            if isinstance(mill_device, Heater)
        ]
        async_add_entities(
            MillNumber(mill_data_coordinator, mill_device) for mill_device in heaters
        )
        async_add_entities(
            MillPowerLimitNumber(mill_data_coordinator, mill_device)
            for mill_device in heaters
        )


def _reported_settings(device: MillDevice) -> dict[str, Any]:
    """Return the settings the heater last reported to the Mill cloud."""
    return (device.data or {}).get("deviceSettings", {}).get("reported", {})


def _setting(device: MillDevice, key: str) -> Any:
    """Return a setting, preferring a recent write the heater has not reported yet."""
    reported = _reported_settings(device).get(key)
    pending = _pending.get((device.device_id, key))
    if pending is None:
        return reported
    value, written_at = pending
    if reported == value or dt_util.utcnow() - written_at > PENDING_TIMEOUT:
        del _pending[(device.device_id, key)]
        return reported
    return value


def _set_pending(device_id: str, key: str, value: float) -> None:
    """Remember a setting written to the cloud until the heater reports it."""
    _pending[(device_id, key)] = (value, dt_util.utcnow())


class MillNumber(MillBaseEntity, NumberEntity):
    """Rated power of the heater.

    The Mill cloud stores this as ``max_heater_power``. It describes what the
    heater can draw and is used by its PID regulator; it does not cap the
    power. Use ``MillPowerLimitNumber`` to limit the heater.
    """

    _attr_device_class = NumberDeviceClass.POWER
    _attr_name = "Rated power"
    _attr_native_max_value = 2000
    _attr_native_min_value = 0
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(
        self,
        coordinator: MillDataUpdateCoordinator,
        mill_device: MillDevice,
    ) -> None:
        """Initialize the number."""
        self._attr_unique_id = f"{mill_device.device_id}_max_heating_power"
        super().__init__(coordinator, mill_device)

    @callback
    @override
    def _update_attr(self, device: MillDevice) -> None:
        self._attr_native_value = _setting(device, "max_heater_power")
        self._available = device.available and self._attr_native_value is not None

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.coordinator.mill_data_connection.max_heating_power(self._id, value)
        _set_pending(self._id, "max_heater_power", value)
        self._attr_native_value = value
        self.async_write_ha_state()


class MillPowerLimitNumber(MillBaseEntity, NumberEntity):
    """Power limit of the heater, in watts.

    The Mill cloud takes the limit as ``limited_heating_power``, a percentage
    of the rated power (``max_heater_power``). This is the setting behind
    "PID controller > Adjust Wattage" in the Mill app.
    """

    _attr_device_class = NumberDeviceClass.POWER
    _attr_name = "Power limit"
    _attr_native_min_value = 0
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(
        self,
        coordinator: MillDataUpdateCoordinator,
        mill_device: MillDevice,
    ) -> None:
        """Initialize the number."""
        self._attr_unique_id = f"{mill_device.device_id}_power_limit"
        self._rated_power: float | None = None
        super().__init__(coordinator, mill_device)

    @callback
    @override
    def _update_attr(self, device: MillDevice) -> None:
        self._rated_power = _setting(device, "max_heater_power")
        percent = _setting(device, "limited_heating_power")
        if self._rated_power and percent is not None:
            self._attr_native_max_value = self._rated_power
            self._attr_native_value = round(self._rated_power * percent / 100)
        else:
            self._attr_native_value = None
        self._available = device.available and self._attr_native_value is not None

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the power limit as a percentage of the rated power."""
        if not self._rated_power:
            return
        percent = min(max(round(value / self._rated_power * 100), 1), 100)
        connection = self.coordinator.mill_data_connection
        payload = {
            "deviceType": connection.devices[self._id].device_type,
            "enabled": True,
            "settings": {
                "operation_mode": MODE_INDIVIDUAL,
                "limited_heating_power": percent,
            },
        }
        if await connection.request(
            f"devices/{self._id}/settings", payload, patch=True
        ):
            # The library caches device reads for up to 20 minutes; drop the cache
            # so the next refresh shows the new limit instead of the old one.
            getattr(connection, "_cached_data", {}).clear()
            _set_pending(self._id, "limited_heating_power", percent)
            self._attr_native_value = round(self._rated_power * percent / 100)
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
