# Spatial Bluetooth

> **Vorlaeufige Beschreibung.** Aus CHANGELOG und Quelltext rekonstruiert, nicht die Originalfassung des Autors -- diese liegt auf GitHub und wird hier ersetzt, sobald sie verfuegbar ist.


Spatial-Hub-Provider fuer Bluetooth-Geraete und die Empfaenger, die sie sehen.

Diese Integration meldet dem [Spatial Hub](https://gitlab.schanz.ipv64.net/chance-konstruktion/ha-spatial-hub) Bluetooth-Geraete und die Empfaenger, die sie sehen,
damit sie auf dem Grundriss auftauchen. Sie ist eine ganz normale Home
Assistant-Integration und laeuft auch dann, wenn der Hub gar nicht
installiert ist -- dann passiert schlicht nichts.

## Was hier als Kante gemeldet wird

Welcher Proxy empfaengt welches Geraet, mit welcher Feldstaerke. Bluetooth hat keine Topologie, aber es hat Naehe -- und Naehe ist auf einem Grundriss die interessantere Aussage.

## Stand

**Geruest.** Aufbau, Manifest, Config Flow und der Provider-Shim stehen.
Was noch fehlt, ist die Funktion `_spatial_data()` in
[`custom_components/spatial_bluetooth/__init__.py`](custom_components/spatial_bluetooth/__init__.py):
Sie liefert derzeit eine leere Liste, weil das Auslesen der Topologie fuer
jeden Transport anders aussieht.

Die Integration ist damit installierbar und tut nichts Falsches -- sie hat
nur noch nichts zu erzaehlen.

## Installation

Ueber HACS als benutzerdefiniertes Repository, oder von Hand:
`custom_components/spatial_bluetooth/` nach `config/custom_components/` kopieren und
Home Assistant neu starten.

## Warum nichts aus `spatial_hub` importiert wird

Die Datei `spatial_hub_provider.py` ist eine **Kopie** aus dem Hub, kein
Import. Der Hub kann fehlen, in einer anderen Version vorliegen oder
entfernt werden, waehrend diese Integration weiterlaeuft. Der Shim schreibt
nur ein Dict nach `hass.data` und feuert ein Dispatcher-Signal -- beides
kostet nichts, wenn niemand zuhoert.

Naeheres in der [SDK-Dokumentation des Hubs](https://gitlab.schanz.ipv64.net/chance-konstruktion/ha-spatial-hub/-/blob/main/sdk/README.md).

## Lizenz

MIT, siehe [LICENSE](LICENSE).

