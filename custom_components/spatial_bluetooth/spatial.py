"""Bluetooth on the floor plan: who hears what, and how loudly.

Bluetooth is the one radio in the house where Home Assistant already holds
genuinely *spatial* information and nothing draws it. Every BLE
advertisement arrives at one or more receivers -- the adapter in the
server, an ESPHome proxy on a shelf, a Shelly in the hallway -- and each
one records how strong it was. A sensor heard at -55 dBm by the kitchen
proxy and -88 dBm by the cellar one is in the kitchen. That is not an
inference this file has to make: it is what the numbers say, and drawing
them is enough.

So: one node per receiver, one node per device, and an edge from a device
to every receiver that currently hears it. The strongest is solid, the
others dashed, which makes "nearest proxy" readable at a glance without
this file ever claiming to have measured a distance in metres.

Two deliberate limits.

**Only devices this house has adopted.** ``async_discovered_service_info``
returns every advertisement in radio range, which in a terraced street is
the neighbours' phones, three televisions and a hundred beacons that will
never be seen again. Those are not on anybody's floor plan. A device is
drawn when Home Assistant has a device registry entry for its address --
that is exactly the set the user has said yes to.

**Where a receiver sits comes from the user, not from us.** A proxy's
source is its MAC, the same MAC its ESPHome or Shelly device entry carries
as a connection, and that entry already has the area the user put it in.
Nothing here guesses a position.

Everything reads the public ``homeassistant.components.bluetooth`` API and
nothing else. There is no fallback to internals here, because there is
nothing worth falling back to: without the bluetooth integration there are
no receivers, and a layer with no receivers has nothing to say.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.event import async_track_time_interval

from .spatial_hub_provider import anchor, edge, node, spatial_provider

_LOGGER = logging.getLogger(__name__)

# Advertisements arrive constantly and the hub redraws on every notify.
# Half a minute keeps a walking phone roughly honest without turning the
# floor plan into a strobe.
REFRESH = timedelta(seconds=30)

# A house with more adopted BLE devices than this is not a floor plan
# problem any more. The hub caps its own layers for the same reason.
MAX_DEVICES = 250

# BLE RSSI in dBm. A device at one metre reads about -60; below -80 it is
# through a wall or two. Wide bands on purpose -- RSSI jitters several dB
# between two advertisements and a plan that recolours every tick is noise.
_GOOD = -60
_FAIR = -80


def _quality(rssi: Any) -> str:
    """One of the four words every provider speaks, from a dBm reading."""
    try:
        value = float(rssi)
    except (TypeError, ValueError):
        return "unknown"
    if value >= _GOOD:
        return "good"
    if value >= _FAIR:
        return "fair"
    return "poor"


def _api() -> Any:
    """The bluetooth integration's public API, or None if it is not there.

    Core ships it, so the import all but always succeeds -- but an import
    that raises inside ``data()`` would cost the layer, and "no Bluetooth
    in this house" deserves an empty layer rather than an error.
    """
    try:
        from homeassistant.components import bluetooth
    except ImportError:  # pragma: no cover - core always has it
        return None
    return bluetooth


def _norm(address: Any) -> str:
    """One spelling of a MAC, so two sources can be compared at all."""
    return str(address or "").strip().lower().replace("-", ":")


def _devices_by_address(hass: HomeAssistant) -> dict[str, Any]:
    """Every device registry entry, keyed by the MAC it is reachable at.

    Which connection type does not matter. ``bluetooth`` is what a BLE
    integration writes, ``mac`` is what a device that also has an IP
    writes, and an ESPHome proxy is the second kind while being the most
    important thing on this layer. Both are addresses, and the address is
    what the scanner reports.
    """
    try:
        registry = dr.async_get(hass)
    except (AttributeError, KeyError):  # pragma: no cover - registry absent
        return {}

    found: dict[str, Any] = {}
    for device in getattr(registry, "devices", {}).values():
        for connection in getattr(device, "connections", None) or ():
            # Same defensiveness as everywhere else: `connections` is typed
            # as pairs but nothing enforces the length, and unpacking into
            # two names would turn one odd entry into a dead layer.
            if not isinstance(connection, (tuple, list)) or len(connection) < 2:
                continue
            address = _norm(connection[1])
            if address:
                found.setdefault(address, device)
    return found


def _representative(hass: HomeAssistant, device: Any) -> str | None:
    """One entity to stand for a device, so its popup has a door.

    Without an entity_id the hub's popup is a card with a name on it and
    nothing to open. Diagnostics sort last: "Signal strength" is a poor
    answer to "show me this sensor".
    """
    if device is None:
        return None
    try:
        registry = er.async_get(hass)
    except (AttributeError, KeyError):  # pragma: no cover
        return None
    entries = [
        entry
        for entry in getattr(registry, "entities", {}).values()
        if getattr(entry, "device_id", None) == device.id
        and not getattr(entry, "disabled_by", None)
    ]
    if not entries:
        return None
    return sorted(
        entries,
        key=lambda entry: (
            getattr(entry, "entity_category", None) is not None,
            entry.entity_id,
        ),
    )[0].entity_id


def _scanners(hass: HomeAssistant, bluetooth: Any) -> dict[str, dict[str, Any]]:
    """Every receiver currently registered, keyed by its source.

    The source is the string every advertisement is tagged with, so it is
    what the edges have to point at. A remote scanner's source is its MAC,
    which is how a proxy finds its own device entry -- and with it the room
    the user already put it in.
    """
    try:
        current = bluetooth.async_current_scanners(hass)
    except (AttributeError, KeyError, RuntimeError):
        # Older Home Assistant, or bluetooth set up but not started.
        _LOGGER.debug("no Bluetooth scanners to ask about", exc_info=True)
        return {}

    by_address = _devices_by_address(hass)
    scanners: dict[str, dict[str, Any]] = {}
    for scanner in current:
        source = str(getattr(scanner, "source", "") or "")
        if not source:
            continue
        device = by_address.get(_norm(source))
        # A scanner that is registered but not scanning is a proxy that has
        # gone quiet -- worth seeing, and worth not colouring green.
        scanning = getattr(scanner, "scanning", True)
        scanners[source] = {
            "id": f"scanner-{source}",
            "device": device,
            "node": node(
                f"scanner-{source}",
                label=str(
                    getattr(scanner, "name", "") or getattr(device, "name", "") or source
                ),
                area_id=getattr(device, "area_id", None),
                entity_id=_representative(hass, device),
                state="online" if scanning else "offline",
                icon="mdi:bluetooth-audio" if scanning else "mdi:bluetooth-off",
                rolle="Empfänger",
                quelle=source,
                adapter=str(getattr(scanner, "adapter", "") or ""),
                # A non-connectable scanner hears everything and can talk to
                # nothing. That is a real difference when a sensor will not
                # pair, and it is invisible everywhere else.
                verbindungsfaehig="ja" if getattr(scanner, "connectable", False) else "nein",
                aktiv="ja" if scanning else "nein",
            ),
        }
    return scanners


def _heard_by(bluetooth: Any, hass: HomeAssistant, address: str) -> list[tuple[str, Any]]:
    """Which receivers hear this address right now, and at what RSSI.

    This is the whole point of the layer. ``async_scanner_devices_by_address``
    is the only place in Home Assistant where the same device is reported
    per receiver rather than collapsed to the best one.
    """
    try:
        found = bluetooth.async_scanner_devices_by_address(
            hass, address, connectable=False
        )
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return []

    readings: list[tuple[str, Any]] = []
    for entry in found or ():
        source = str(getattr(getattr(entry, "scanner", None), "source", "") or "")
        if not source:
            continue
        advertisement = getattr(entry, "advertisement", None)
        rssi = getattr(advertisement, "rssi", None)
        if rssi is None:
            rssi = getattr(getattr(entry, "ble_device", None), "rssi", None)
        readings.append((source, rssi))
    return readings


def _rssi_key(reading: tuple[str, Any]) -> float:
    """Sort strongest first, with 'no reading' always last."""
    try:
        return -float(reading[1])
    except (TypeError, ValueError):
        return float("inf")


# How much better a different receiver has to be before a device is said to
# have changed rooms. BLE RSSI jitters by several dB between two
# advertisements from a device that has not moved at all, so without a
# margin a thermometer on a shelf hops between kitchen and hallway every
# thirty seconds and the floor plan becomes a liar with an animation.
_HYSTERESIS = 6.0


def _rssi(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nearest(
    settled: dict[str, str], address: str, readings: list[tuple[str, Any]]
) -> str | None:
    """Which receiver this device counts as being at, with hysteresis.

    The strongest receiver is the answer, but only once it is *clearly* the
    strongest: while the previous one is still within a few dB it keeps the
    device. That is what turns a jittering number into a room.
    """
    usable = [(source, _rssi(value)) for source, value in readings]
    usable = [(source, value) for source, value in usable if value is not None]
    if not usable:
        return None

    best_source, best_value = usable[0]
    previous = settled.get(address)
    for source, value in usable:
        if source == previous and best_value - value < _HYSTERESIS:
            best_source = source
            break
    settled[address] = best_source
    return best_source


# The path loss exponent: how fast signal falls off with distance. 2.0 is
# free space, a furnished house is 2.5 to 4 depending on how many walls
# are in the way. 2.5 is the conservative end, chosen on purpose -- a
# higher figure makes the nearest receiver dominate more sharply, which
# looks decisive and is exactly the confidence this data does not have.
_PATH_LOSS = 2.5


def _weight(rssi: float) -> float:
    """Turn a dBm reading into "how near", for the hub to average.

    From the log-distance path loss model: ``d = 10^((P - RSSI)/(10n))``.
    Weighting by ``1/d`` makes the weight proportional to
    ``10^(RSSI/(10n))`` -- and the transmit power ``P``, which is per
    device, unknown, and the reason naive RSSI ranging is so bad, cancels
    out entirely. That is the one thing that makes this defensible: the
    result depends on the *differences* between receivers hearing the same
    transmitter, never on an absolute calibration nobody performed.

    ``1/d`` rather than ``1/d²`` deliberately. The inverse square is the
    honest physics for power, and it is also what makes the estimate snap
    onto whichever receiver happens to be loudest this second. Room-level
    is the claim; a gentler weighting is the one that keeps it.
    """
    return 10 ** (rssi / (10.0 * _PATH_LOSS))


def _confidence(readings: list[tuple[str, Any]], chosen: str | None) -> str:
    """How much this room assignment is actually worth.

    Stated rather than implied. One receiver gives a direction and no
    place; two that disagree by 2 dB give a coin flip. A plan that draws
    all three the same way is claiming a precision nobody measured.
    """
    if chosen is None:
        return "keine"
    values = sorted(
        (value for _, value in ((s, _rssi(v)) for s, v in readings) if value is not None),
        reverse=True,
    )
    if len(values) < 2:
        return "gering (nur ein Empfänger)"
    margin = values[0] - values[1]
    if margin >= 10:
        return "hoch"
    return "mittel" if margin >= 4 else "gering"


def async_setup_spatial(hass: HomeAssistant, entry: Any) -> None:
    # Which receiver each device was last settled at. Kept across refreshes
    # because hysteresis is meaningless without a memory of the last answer.
    settled: dict[str, str] = {}

    def data() -> dict[str, list]:
        bluetooth = _api()
        if bluetooth is None:
            return {"nodes": [], "edges": []}

        scanners = _scanners(hass, bluetooth)
        if not scanners:
            return {"nodes": [], "edges": []}

        by_address = _devices_by_address(hass)
        # A receiver is drawn as a receiver, never a second time as one of
        # the things being heard -- proxies advertise too.
        own = {_norm(source) for source in scanners}

        try:
            discovered = list(
                bluetooth.async_discovered_service_info(hass, connectable=False)
            )
        except (AttributeError, KeyError, RuntimeError, TypeError):
            _LOGGER.debug("no Bluetooth advertisements to read", exc_info=True)
            discovered = []

        nodes = [scanner["node"] for scanner in scanners.values()]
        edges = []
        drawn = 0

        seen: set[str] = set()
        for info in discovered:
            address = _norm(getattr(info, "address", ""))
            if not address or address in seen or address in own:
                continue
            seen.add(address)
            device = by_address.get(address)
            # The adoption test. Everything the neighbours own is in this
            # list too, and none of it belongs on this floor plan.
            if device is None:
                continue
            if drawn >= MAX_DEVICES:
                break
            drawn += 1

            readings = sorted(_heard_by(bluetooth, hass, address), key=_rssi_key)
            readings = [item for item in readings if item[0] in scanners]
            best = readings[0] if readings else (None, getattr(info, "rssi", None))
            node_id = f"device-{address}"

            # Room-level localisation, which is the honest half of the
            # question "where is this thing". The device sits in the room of
            # the receiver that hears it loudest -- *unless* the user has
            # already said where it is. An explicit area is a statement,
            # not a default, and a thermometer screwed to the bathroom wall
            # must not migrate to the kitchen because the door was open.
            nearest = _nearest(settled, address, readings)
            heard_in = None
            if nearest is not None:
                heard_in = getattr(scanners[nearest]["device"], "area_id", None)
            stated = getattr(device, "area_id", None)
            area_id = stated or heard_in

            # And the finer answer: a point between the receivers rather
            # than a room. Only offered when the user has *not* said where
            # this device is -- anchors would otherwise pull a thermometer
            # off the bathroom wall it is screwed to, and contradict the
            # area right next to it in the same payload.
            anchors = []
            if stated is None:
                anchors = [
                    anchor(f"scanner-{source}", _weight(value))
                    for source, value in (
                        (source, _rssi(raw)) for source, raw in readings
                    )
                    if value is not None
                ]

            nodes.append(
                node(
                    node_id,
                    label=getattr(device, "name_by_user", None)
                    or getattr(device, "name", "")
                    or str(getattr(info, "name", "") or address),
                    area_id=area_id,
                    anchors=anchors,
                    entity_id=_representative(hass, device),
                    state="online",
                    icon="mdi:bluetooth",
                    rolle="Gerät",
                    adresse=address,
                    hersteller=getattr(device, "manufacturer", "") or "",
                    modell=getattr(device, "model", "") or "",
                    rssi=best[1],
                    # The number that says whether the plan can be trusted
                    # here: one receiver is a direction, three are a place.
                    empfaenger=len(readings),
                    # Always stated, even when the user's own area won, so
                    # the popup can answer "where is it *right now*" for a
                    # device that is nailed to a wall on paper.
                    gehoert_bei=(
                        scanners[nearest]["node"]["label"] if nearest else ""
                    ),
                    genauigkeit=_confidence(readings, nearest),
                    # Says which of the two answers the dot is standing on,
                    # so nobody mistakes a guess for a placement.
                    ortung=(
                        "Nutzer" if stated
                        else "Signalstärke" if anchors or heard_in
                        else "keine"
                    ),
                )
            )

            for index, (source, rssi) in enumerate(readings):
                if source not in scanners:
                    continue
                edges.append(
                    edge(
                        node_id,
                        f"scanner-{source}",
                        value=rssi,
                        quality=_quality(rssi),
                        # Solid to the receiver that hears it best, dashed
                        # to the rest. The solid line is the one that says
                        # where the device probably is; the dashed ones say
                        # how sure that is.
                        dashed=index > 0,
                        staerkster="ja" if index == 0 else "nein",
                    )
                )

        return {"nodes": nodes, "edges": edges}

    provider = spatial_provider(
        hass,
        entry,
        name="Bluetooth",
        icon="mdi:bluetooth",
        data=data,
        version="260808",
    )

    # The bluetooth integration fires no dispatcher signal this file could
    # subscribe to without registering a callback for every address in the
    # house, so a slow tick is the honest option.
    entry.async_on_unload(
        async_track_time_interval(
            hass, lambda _now: provider.async_notify(), REFRESH
        )
    )
