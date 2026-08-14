"""Der volle Konformitaetssatz, gegen eine NICHT leere Nutzlast.

Die Suite nebenan prueft den Weg ohne Bluetooth -- den Ausfallpfad. Dort
ist die Nutzlast leer, und eine leere Liste erfuellt jeden Vertrag
muehelos: keine Kennung kann wackeln, keine Kante ins Leere zeigen, keine
Metadaten sich dem Websocket verweigern, kein Anker ein unsinniges
Gewicht tragen. Sie beweist nichts.

Was hier gestellt wird, ist genau **drei Funktionen** der
Bluetooth-Integration -- die drei, die diese Ebene ueberhaupt liest. Sie
brauchen im Betrieb einen Adapter und Funkverkehr, und beides laesst sich
in einer CI nicht ehrlich nachstellen. Alles andere ist echt: echtes
``hass``, echtes Geraeteregister mit den Proxys darin, echte Bereiche.

Der Aufbau ist der Fall, fuer den es diese Ebene gibt: ein Anhaenger, den
zwei Proxys in zwei Raeumen unterschiedlich laut hoeren. Daraus muessen
Anker mit deutlich verschiedenen Gewichten werden -- sonst ist die
Messung weggeworfen und der Punkt landet zwischen den Raeumen.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from spatial_hub_conformance import SpatialHubConformance

EIGENE_DOMAIN = "spatial_bluetooth"

KUECHE_MAC = "AA:BB:CC:00:00:01"
KELLER_MAC = "AA:BB:CC:00:00:02"
ANHAENGER = "11:22:33:44:55:66"


def _scanner(source: str, name: str):
    return SimpleNamespace(source=source, name=name, scanning=True,
                           connectable=False)


def _messung(source: str, rssi: int):
    """Ein Treffer, wie ihn async_scanner_devices_by_address liefert."""
    return SimpleNamespace(
        scanner=SimpleNamespace(source=source),
        advertisement=SimpleNamespace(rssi=rssi),
        ble_device=SimpleNamespace(rssi=rssi),
    )


@pytest.fixture
def funkhaus(hass: HomeAssistant, enable_custom_integrations, monkeypatch):
    """Zwei Proxys in zwei Raeumen und ein Anhaenger, den beide hoeren."""
    bereiche = ar.async_get(hass)
    kueche = bereiche.async_create("Küche")
    keller = bereiche.async_create("Keller")

    # Die Proxys sind echte Geraete -- ihr Raum kommt vom Nutzer, und
    # genau darauf stuetzt sich die ganze Verortung.
    fremd = MockConfigEntry(domain="esphome", title="ESPHome")
    fremd.add_to_hass(hass)
    geraete = dr.async_get(hass)
    for mac, bereich, name in (
        (KUECHE_MAC, kueche.id, "Proxy Küche"),
        (KELLER_MAC, keller.id, "Proxy Keller"),
    ):
        geraet = geraete.async_get_or_create(
            config_entry_id=fremd.entry_id,
            connections={(dr.CONNECTION_NETWORK_MAC, mac.lower())},
            identifiers={("esphome", mac)},
            name=name,
        )
        geraete.async_update_device(geraet.id, area_id=bereich)

    # Der Anhaenger selbst ist ebenfalls adoptiert -- sonst zeichnet
    # die Ebene ihn bewusst nicht, und die Nutzlast bliebe leer.
    geraete.async_get_or_create(
        config_entry_id=fremd.entry_id,
        connections={(dr.CONNECTION_BLUETOOTH, ANHAENGER.lower())},
        identifiers={("demo", ANHAENGER)},
        name="Schlüsselbund",
    )

    monkeypatch.setattr(
        bluetooth, "async_current_scanners",
        lambda _hass: [_scanner(KUECHE_MAC, "Proxy Küche"),
                       _scanner(KELLER_MAC, "Proxy Keller")],
        raising=False,
    )
    monkeypatch.setattr(
        bluetooth, "async_discovered_service_info",
        lambda _hass, connectable=False: [
            SimpleNamespace(address=ANHAENGER, name="Schlüsselbund",
                            rssi=-55)
        ],
        raising=False,
    )
    monkeypatch.setattr(
        bluetooth, "async_scanner_devices_by_address",
        lambda _hass, address, connectable=False: (
            [_messung(KUECHE_MAC, -55), _messung(KELLER_MAC, -88)]
            if address.lower() == ANHAENGER.lower() else []
        ),
        raising=False,
    )

    return hass


def _anmeldung(hass: HomeAssistant) -> dict:
    from custom_components.spatial_bluetooth.spatial import async_setup_spatial

    eigener = MockConfigEntry(domain=EIGENE_DOMAIN, title="Spatial Bluetooth")
    eigener.add_to_hass(hass)
    async_setup_spatial(hass, eigener)
    return hass.data["spatial_hub_providers"][EIGENE_DOMAIN]


class TestKonformitaetMitInhalt(SpatialHubConformance):
    """Der Satz aus dem SDK an einem Haus, in dem etwas funkt.

    Faellt diese Klasse, ist der Adapter vom Vertrag abgewichen -- nicht
    der Vertrag vom Adapter.
    """

    @pytest.fixture(autouse=True)
    def _binden(self, funkhaus):
        self._hass = funkhaus
        yield

    def build_registration(self):
        return _anmeldung(self._hass)


def test_der_anhaenger_wird_am_lauteren_proxy_verankert(funkhaus) -> None:
    """Die Gegenprobe, und der eigentliche Grund fuer diese Datei.

    Ein Konformitaetssatz ueber einer leeren Liste ist gruen und sagt
    nichts. Ginge die Vorrichtung oben still kaputt -- kein Proxy mehr,
    keine Messung mehr -- bliebe er gruen, waehrend er nichts prueft.

    Deshalb wird hier ausdruecklich behauptet, was drinstehen muss: der
    Anhaenger haengt an beiden Proxys, und die Kueche zieht deutlich
    staerker als der Keller. Genau das ist die Aussage, die aus -55 gegen
    -88 dBm folgt.
    """
    nutzlast = _anmeldung(funkhaus)["data"]()
    knoten = {k["id"]: k for k in nutzlast["nodes"]}

    anhaenger = next(
        k for kennung, k in knoten.items()
        if ANHAENGER.lower() in kennung.lower()
    )
    anker = {a["id"]: a["weight"] for a in anhaenger["anchors"]}

    assert len(anker) == 2, f"beide Proxys erwartet, bekommen: {sorted(anker)}"
    kueche = anker[f"scanner-{KUECHE_MAC}"]
    keller = anker[f"scanner-{KELLER_MAC}"]
    assert kueche > 2 * keller, (
        f"-55 dBm muss deutlich staerker ziehen als -88 dBm, "
        f"ist aber {kueche:.3f} gegen {keller:.3f}"
    )
