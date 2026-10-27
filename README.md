# ALDI AutoRefill – kostenlose GitHub-Version

Dieses kleine Programm prüft alle 15 Minuten das Inlands-Datenvolumen im
ALDI-TALK-Kundenportal. Bei einer geschützten, nicht veröffentlichten Grenze
verlangt es genau einen passenden sichtbaren und klickbaren Nachbuch-Schalter,
klickt höchstens einmal und prüft anschließend, ob das Volumen gestiegen ist.

## Datenschutz

Im öffentlichen Projekt liegen nur der Programmcode und diese Anleitung. Die
ALDI-Anmeldung gehört ausschließlich in das verschlüsselte GitHub-Geheimnis
`ALDI_STORAGE_STATE_B64`. Die Dateien `.aldi-session.json` und
`.aldi-session.b64` dürfen nie hochgeladen oder weitergegeben werden.

Die öffentlichen Protokolle nennen nur Zustände wie `MONITORING`, `COOLDOWN`
oder `CONFIRMED`. Telefonnummer, Guthaben und das genaue Restvolumen werden dort
nicht ausgegeben.

## Sicherheitsregeln

- nur die echte Domain `alditalk-kundenportal.de`
- nur genau ein sichtbarer, passender Nachbuch-Schalter
- erneute Prüfung direkt vor dem Klick
- 30 Minuten Sperrzeit nach jedem Klickversuch
- keine Screenshots und keine gespeicherten Portalseiten
- keine parallelen Läufe

## Einrichtung

Die Einrichtung erfolgt einmalig am Mac: bestehende Anmeldung exportieren,
Projekt öffentlich auf GitHub anlegen, die exportierte Sitzung als
verschlüsseltes Geheimnis speichern und einen manuellen Testlauf starten.
Danach kann der Mac ausgeschaltet bleiben.

GitHub kann geplante Läufe gelegentlich verspätet starten. Bei öffentlichen
Projekten wird der Zeitplan außerdem nach 60 Tagen ohne Projektaktivität
deaktiviert und muss dann einmal wieder eingeschaltet werden.
