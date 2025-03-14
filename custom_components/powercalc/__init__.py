"""The PowerCalc integration."""

from __future__ import annotations

import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from awesomeversion.awesomeversion import AwesomeVersion
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.utility_meter import DEFAULT_OFFSET, max_28_days
from homeassistant.components.utility_meter.const import METER_TYPES
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    CONF_DOMAIN,
    CONF_ENTITIES,
    CONF_SCAN_INTERVAL,
    EVENT_HOMEASSISTANT_STARTED,
    Platform,
)
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.discovery import async_load_platform

from .common import validate_name_pattern
from .const import (
    CONF_CREATE_DOMAIN_GROUPS,
    CONF_CREATE_ENERGY_SENSORS,
    CONF_CREATE_UTILITY_METERS,
    CONF_DISABLE_EXTENDED_ATTRIBUTES,
    CONF_ENABLE_AUTODISCOVERY,
    CONF_ENERGY_INTEGRATION_METHOD,
    CONF_ENERGY_SENSOR_CATEGORY,
    CONF_ENERGY_SENSOR_FRIENDLY_NAMING,
    CONF_ENERGY_SENSOR_NAMING,
    CONF_ENERGY_SENSOR_PRECISION,
    CONF_ENERGY_SENSOR_UNIT_PREFIX,
    CONF_FORCE_UPDATE_FREQUENCY,
    CONF_IGNORE_UNAVAILABLE_STATE,
    CONF_POWER_SENSOR_CATEGORY,
    CONF_POWER_SENSOR_FRIENDLY_NAMING,
    CONF_POWER_SENSOR_NAMING,
    CONF_POWER_SENSOR_PRECISION,
    CONF_SENSOR_TYPE,
    CONF_UTILITY_METER_OFFSET,
    CONF_UTILITY_METER_TARIFFS,
    CONF_UTILITY_METER_TYPES,
    DATA_CALCULATOR_FACTORY,
    DATA_CONFIGURED_ENTITIES,
    DATA_DISCOVERED_ENTITIES,
    DATA_DOMAIN_ENTITIES,
    DATA_USED_UNIQUE_IDS,
    DEFAULT_ENERGY_INTEGRATION_METHOD,
    DEFAULT_ENERGY_NAME_PATTERN,
    DEFAULT_ENERGY_SENSOR_PRECISION,
    DEFAULT_ENTITY_CATEGORY,
    DEFAULT_POWER_NAME_PATTERN,
    DEFAULT_POWER_SENSOR_PRECISION,
    DEFAULT_UPDATE_FREQUENCY,
    DEFAULT_UTILITY_METER_TYPES,
    DISCOVERY_TYPE,
    DOMAIN,
    DOMAIN_CONFIG,
    ENERGY_INTEGRATION_METHODS,
    ENTITY_CATEGORIES,
    MIN_HA_VERSION,
    PowercalcDiscoveryType,
    SensorType,
    UnitPrefix,
)
from .discovery import DiscoveryManager
from .sensors.group import (
    remove_group_from_power_sensor_entry,
    remove_power_sensor_from_associated_groups,
)
from .strategy.factory import PowerCalculatorStrategyFactory

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            cv.deprecated(
                CONF_SCAN_INTERVAL, replacement_key=CONF_FORCE_UPDATE_FREQUENCY
            ),
            vol.Schema(
                {
                    vol.Optional(
                        CONF_FORCE_UPDATE_FREQUENCY, default=DEFAULT_UPDATE_FREQUENCY
                    ): cv.time_period,
                    vol.Optional(
                        CONF_POWER_SENSOR_NAMING, default=DEFAULT_POWER_NAME_PATTERN
                    ): validate_name_pattern,
                    vol.Optional(
                        CONF_POWER_SENSOR_FRIENDLY_NAMING
                    ): validate_name_pattern,
                    vol.Optional(
                        CONF_POWER_SENSOR_CATEGORY, default=DEFAULT_ENTITY_CATEGORY
                    ): vol.In(ENTITY_CATEGORIES),
                    vol.Optional(
                        CONF_ENERGY_SENSOR_NAMING, default=DEFAULT_ENERGY_NAME_PATTERN
                    ): validate_name_pattern,
                    vol.Optional(
                        CONF_ENERGY_SENSOR_FRIENDLY_NAMING
                    ): validate_name_pattern,
                    vol.Optional(
                        CONF_ENERGY_SENSOR_CATEGORY, default=DEFAULT_ENTITY_CATEGORY
                    ): vol.In(ENTITY_CATEGORIES),
                    vol.Optional(
                        CONF_DISABLE_EXTENDED_ATTRIBUTES, default=False
                    ): cv.boolean,
                    vol.Optional(CONF_ENABLE_AUTODISCOVERY, default=True): cv.boolean,
                    vol.Optional(CONF_CREATE_ENERGY_SENSORS, default=True): cv.boolean,
                    vol.Optional(CONF_CREATE_UTILITY_METERS, default=False): cv.boolean,
                    vol.Optional(CONF_UTILITY_METER_TARIFFS, default=[]): vol.All(
                        cv.ensure_list, [cv.string]
                    ),
                    vol.Optional(
                        CONF_UTILITY_METER_TYPES, default=DEFAULT_UTILITY_METER_TYPES
                    ): vol.All(cv.ensure_list, [vol.In(METER_TYPES)]),
                    vol.Optional(
                        CONF_UTILITY_METER_OFFSET, default=DEFAULT_OFFSET
                    ): vol.All(cv.time_period, cv.positive_timedelta, max_28_days),
                    vol.Optional(
                        CONF_ENERGY_INTEGRATION_METHOD,
                        default=DEFAULT_ENERGY_INTEGRATION_METHOD,
                    ): vol.In(ENERGY_INTEGRATION_METHODS),
                    vol.Optional(
                        CONF_ENERGY_SENSOR_PRECISION,
                        default=DEFAULT_ENERGY_SENSOR_PRECISION,
                    ): cv.positive_int,
                    vol.Optional(
                        CONF_POWER_SENSOR_PRECISION,
                        default=DEFAULT_POWER_SENSOR_PRECISION,
                    ): cv.positive_int,
                    vol.Optional(
                        CONF_ENERGY_SENSOR_UNIT_PREFIX, default=UnitPrefix.KILO
                    ): vol.In([cls.value for cls in UnitPrefix]),
                    vol.Optional(CONF_CREATE_DOMAIN_GROUPS, default=[]): vol.All(
                        cv.ensure_list, [cv.string]
                    ),
                    vol.Optional(CONF_IGNORE_UNAVAILABLE_STATE): cv.boolean,
                }
            ),
        )
    },
    extra=vol.ALLOW_EXTRA,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    if AwesomeVersion(HA_VERSION) < AwesomeVersion(MIN_HA_VERSION):
        msg = (
            "This integration require at least HomeAssistant version "
            f" {MIN_HA_VERSION}, you are running version {HA_VERSION}."
            " Please upgrade HomeAssistant to continue use this integration."
        )
        _notify_message(hass, "inv_ha_version", "PowerCalc", msg)
        _LOGGER.critical(msg)
        return False

    domain_config = config.get(DOMAIN) or {
        CONF_POWER_SENSOR_NAMING: DEFAULT_POWER_NAME_PATTERN,
        CONF_POWER_SENSOR_PRECISION: DEFAULT_POWER_SENSOR_PRECISION,
        CONF_POWER_SENSOR_CATEGORY: DEFAULT_ENTITY_CATEGORY,
        CONF_ENERGY_INTEGRATION_METHOD: DEFAULT_ENERGY_INTEGRATION_METHOD,
        CONF_ENERGY_SENSOR_NAMING: DEFAULT_ENERGY_NAME_PATTERN,
        CONF_ENERGY_SENSOR_PRECISION: DEFAULT_ENERGY_SENSOR_PRECISION,
        CONF_ENERGY_SENSOR_CATEGORY: DEFAULT_ENTITY_CATEGORY,
        CONF_ENERGY_SENSOR_UNIT_PREFIX: UnitPrefix.KILO,
        CONF_FORCE_UPDATE_FREQUENCY: DEFAULT_UPDATE_FREQUENCY,
        CONF_DISABLE_EXTENDED_ATTRIBUTES: False,
        CONF_IGNORE_UNAVAILABLE_STATE: False,
        CONF_CREATE_DOMAIN_GROUPS: [],
        CONF_CREATE_ENERGY_SENSORS: True,
        CONF_CREATE_UTILITY_METERS: False,
        CONF_ENABLE_AUTODISCOVERY: True,
        CONF_UTILITY_METER_OFFSET: DEFAULT_OFFSET,
        CONF_UTILITY_METER_TYPES: DEFAULT_UTILITY_METER_TYPES,
    }

    hass.data[DOMAIN] = {
        DATA_CALCULATOR_FACTORY: PowerCalculatorStrategyFactory(hass),
        DOMAIN_CONFIG: domain_config,
        DATA_CONFIGURED_ENTITIES: {},
        DATA_DOMAIN_ENTITIES: {},
        DATA_DISCOVERED_ENTITIES: {},
        DATA_USED_UNIQUE_IDS: [],
    }

    if domain_config.get(CONF_ENABLE_AUTODISCOVERY):
        discovery_manager = DiscoveryManager(hass, config)
        await discovery_manager.start_discovery()

    if domain_config.get(CONF_CREATE_DOMAIN_GROUPS):

        async def _create_domain_groups(event: None):
            await create_domain_groups(
                hass,
                domain_config,
                domain_config.get(CONF_CREATE_DOMAIN_GROUPS),
            )

        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED,
            _create_domain_groups,
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Powercalc integration from a config entry."""

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_entry))
    return True


async def async_update_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update a given config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )

    if unload_ok:
        used_unique_ids: list[str] = hass.data[DOMAIN][DATA_USED_UNIQUE_IDS]
        try:
            used_unique_ids.remove(config_entry.unique_id)
        except ValueError:
            return True

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Called after a config entry is removed."""
    updated_entries: list[ConfigEntry] = []

    sensor_type = config_entry.data.get(CONF_SENSOR_TYPE)
    if sensor_type == SensorType.VIRTUAL_POWER:
        updated_entries = await remove_power_sensor_from_associated_groups(
            hass, config_entry
        )
    if sensor_type == SensorType.GROUP:
        updated_entries = await remove_group_from_power_sensor_entry(hass, config_entry)

    for entry in updated_entries:
        if entry.state == ConfigEntryState.LOADED:
            await hass.config_entries.async_reload(entry.entry_id)


async def create_domain_groups(
    hass: HomeAssistant, global_config: dict, domains: list[str]
):
    """Create group sensors aggregating all power sensors from given domains"""
    _LOGGER.debug("Setting up domain based group sensors..")
    for domain in domains:
        if domain not in hass.data[DOMAIN].get(DATA_DOMAIN_ENTITIES):
            _LOGGER.error(f"Cannot setup group for domain {domain}, no entities found")
            continue

        domain_entities = hass.data[DOMAIN].get(DATA_DOMAIN_ENTITIES)[domain]

        hass.async_create_task(
            async_load_platform(
                hass,
                SENSOR_DOMAIN,
                DOMAIN,
                {
                    DISCOVERY_TYPE: PowercalcDiscoveryType.DOMAIN_GROUP,
                    CONF_ENTITIES: domain_entities,
                    CONF_DOMAIN: domain,
                },
                global_config,
            )
        )


def _notify_message(
    hass: HomeAssistant, notification_id: str, title: str, message: str
) -> None:
    """Notify user with persistent notification"""
    hass.async_create_task(
        hass.services.async_call(
            domain="persistent_notification",
            service="create",
            service_data={
                "title": title,
                "message": message,
                "notification_id": f"{DOMAIN}.{notification_id}",
            },
        )
    )
