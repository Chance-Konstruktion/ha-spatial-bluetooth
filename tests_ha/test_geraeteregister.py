"""Das Geraeteregister wird gelesen, ohne die veraltete Mapping-Sicht.

Core hat ``device_registry.devices`` als Abbildung abgekuendigt: jeder
Zugriff ueber ``.values()``, ``.get()`` oder ``[...]`` schreibt eine
Warnung ins Protokoll und hoert in Home Assistant 2027.9 ganz auf zu
arbeiten. Auf einer belebten Anlage stand die Warnung nach neun Minuten
81 Mal im Log.

Der Ersatz ist, ueber das Objekt selbst zu laufen -- dann kommen die
Eintraege heraus. Diese Datei nagelt beide Seiten fest: dass die neue
Form ohne Abbildungszugriff auskommt, und dass die alte Form (bis
2025.8 lieferte das Iterieren die Schluessel) weiterhin verstanden wird.
Die Integration nennt 2024.4 als Untergrenze, also muss beides gelten.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.spatial_bluetooth.spatial import (
    _devices_by_address,
    _registry_entries,
)

EIGENE_DOMAIN = "spatial_bluetooth"


class _Registry:
    """Nur die eine Eigenschaft, die gelesen wird."""

    def __init__(self, devices):
        self.devices = devices


class _NeueSicht:
    """Wie Core seit 2025.9: Iterieren liefert die Eintraege.

    Der Indexzugriff ist mit Absicht verboten. Greift der Code doch
    darauf zu, faellt der Test hin -- und genau dieser Zugriff ist es,
    der auf einer echten Anlage die Warnung erzeugt.
    """

    def __init__(self, eintraege):
        self._eintraege = list(eintraege)

    def __iter__(self):
        return iter(self._eintraege)

    def __bool__(self):
        return bool(self._eintraege)

    def __getitem__(self, schluessel):  # pragma: no cover - darf nie laufen
        raise AssertionError(
            "Indexzugriff auf registry.devices -- genau das ist abgekuendigt"
        )


class _AlteSicht(dict):
    """Wie Core bis 2025.8: Iterieren liefert die Schluessel."""


def test_neue_sicht_ohne_abbildungszugriff():
    eins, zwei = object(), object()
    assert _registry_entries(_Registry(_NeueSicht([eins, zwei]))) == [eins, zwei]


def test_alte_sicht_wird_aufgeloest():
    eins, zwei = object(), object()
    alt = _AlteSicht({"a": eins, "b": zwei})
    assert _registry_entries(_Registry(alt)) == [eins, zwei]


@pytest.mark.parametrize("devices", [None, _NeueSicht([]), _AlteSicht()])
def test_leeres_register_gibt_leere_liste(devices):
    assert _registry_entries(_Registry(devices)) == []


async def test_geraet_wird_ueber_seine_verbindung_gefunden(
    hass: HomeAssistant, enable_custom_integrations
):
    """Der Umbau darf den Zweck der Funktion nicht verlieren.

    Ein echtes Register, ein echtes Geraet mit einer MAC -- und die
    Zuordnung muss es unter genau dieser Adresse fuehren.
    """
    eintrag = MockConfigEntry(domain=EIGENE_DOMAIN, data={})
    eintrag.add_to_hass(hass)

    register = dr.async_get(hass)
    geraet = register.async_get_or_create(
        config_entry_id=eintrag.entry_id,
        connections={(dr.CONNECTION_BLUETOOTH, "AA:BB:CC:00:00:01")},
        name="Proxy Küche",
    )

    gefunden = _devices_by_address(hass)
    assert gefunden.get("aa:bb:cc:00:00:01") is geraet
