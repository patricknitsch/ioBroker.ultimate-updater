# Ultimate Updater für Home Assistant

🇬🇧 [English version](homeassistant.md)

Custom Integration, die den Update-Status deiner Proxmox-Hosts, LXC-Container und VMs aus
**[Ultimate Updater](https://github.com/BassT23/Proxmox) von [@BassT23](https://github.com/BassT23)** in
Home Assistant bringt und Prüfungen und Updates starten lässt. Sie ist das Home-Assistant-Gegenstück zum
ioBroker-Adapter in diesem Repository und nutzt dieselbe Integrations-API v1 – es wird nie automatisch
aktualisiert oder neu gestartet, nur wenn du einen Button drückst oder ein Update installierst.

> **Inoffizielle Community-Integration.** Sie steht in keiner Verbindung zu Ultimate Updater oder der Proxmox Server Solutions GmbH.

## Voraussetzungen

- Home Assistant 2025.2 oder neuer
- Ultimate Updater **5.2 oder neuer** mit aktivierter Web-UI (Standardport `8765`)
- Ein **API-Token** der Integrations-API v1 (nur HTTPS, eigene Berechtigungen). Auf dem Proxmox-Host:
  ```bash
  ultimate-updater-api-token enable
  ultimate-updater-api-token create homeassistant --permissions read,logs,check,update,reboot,cancel
  ```
  Berechtigungen, die du nicht vergeben willst, einfach weglassen (z. B. `read,logs,check` nur für Status und Prüfungen).

## Installation

**HACS:** HACS → ⋮ → *Benutzerdefinierte Repositories* → URL dieses Repositorys mit Typ *Integration* hinzufügen,
dann *Ultimate Updater* installieren und Home Assistant neu starten.

**Manuell:** `custom_components/ultimate_updater` in den Ordner `custom_components` deiner Home-Assistant-Konfiguration
kopieren und Home Assistant neu starten.

Danach unter **Einstellungen → Geräte & Dienste → Integration hinzufügen → Ultimate Updater** die Adresse der Web-UI
und das API-Token eingeben. Wird das Token später widerrufen, fragt Home Assistant nach einem neuen; die Adresse lässt
sich mit *Neu konfigurieren* ändern.

## Geräte und Entitäten

Ein Gerät für die Ultimate-Updater-Instanz und je ein Gerät pro Host / LXC-Container / VM.

| Pro Host/VM/CT | Beschreibung |
|---|---|
| Update-Entität *Pakete* | Offene Paket-Updates – erscheinen unter **Einstellungen → Updates**. *Installieren* startet das Update dieses Systems (Hosts: Node-Update, die Gäste bleiben unberührt). Die „Versionen“ sind Texte: installiert `up to date`, neueste z. B. `7 updates (2 security)`. |
| Sensoren *Sicherheitsupdates*, *Weitere Updates* | Offene Updates (unbekannt bei heruntergefahrenen/nicht erreichbaren Systemen) |
| Binärsensor *Neustart erforderlich* | Das System braucht einen Neustart |
| Button *Auf Updates prüfen* | Prüft dieses System (installiert nichts) |
| Button *Neustart* | Nur wenn Neustart-Buttons in den Optionen erlaubt sind; nutzbar solange ein Neustart nötig ist |
| Diagnose | Erreichbar, Prüfstatus, letzte Prüfung, Zustand des letzten Jobs |

| Instanz | Beschreibung |
|---|---|
| *Sicherheitsupdates* / *Weitere Updates* | Offene Updates aller Systeme |
| *Systeme mit Updates*, *Systeme mit Neustartbedarf*, *Nicht erreichbare Systeme* | Anzahl, die Namen stehen im Attribut `targets` |
| *Zusammenfassung* | z. B. „7 updates on 3 systems, 1 reboot required“; das Attribut `report` enthält den Statusbericht wie die Statusmail von Ultimate Updater (z. B. für eine Benachrichtigung oder eine Markdown-Karte) |
| *Job läuft* | Ein Prüf-/Update-Job läuft |
| Event-Entität *Job beendet* | Feuert, wenn ein Job fertig ist (`completed`, `completed_with_warnings`, `skipped`, `failed`, `interrupted`), auch für Jobs aus der Web-UI. Attribute: `target_name`, `target_id`, `unit`, `job_type`, `exit_code`, `log` (letzte Logzeilen fehlgeschlagener Jobs, braucht die Berechtigung `logs`) |
| *Alle prüfen* | Prüft alle Systeme inklusive Hosts |
| *Alle VMs/CTs aktualisieren* | Aktualisiert alle VMs/CTs nacheinander; Hosts und ausgenommene Systeme werden übersprungen |
| *VMs/CTs mit Sicherheitsupdates aktualisieren* | **Vollständiges** Update der VMs/CTs mit Sicherheitsupdates (Ultimate Updater kennt kein reines Sicherheitsupdate) |
| *Sammel-Update stoppen* | Stoppt ein laufendes Sammel-Update nach dem aktuellen System |
| *Laufenden Job abbrechen* | Bricht den laufenden Job ab |
| *Sammel-Update läuft*, *Fortschritt Sammel-Update* | Fortschritt, z. B. `3/7: web`, am Ende z. B. `4 ok, 1 unchanged, 1 failed, 0 not started` |
| Diagnose | Ultimate-Updater-Version, Update von Ultimate Updater verfügbar, Anzahl Systeme, Zeitpunkt des Status |

Die Entity-IDs entstehen aus den englischen Namen, z. B. `update.web_packages` oder
`event.ultimate_updater_job_finished`, wenn Home Assistant beim Einrichten auf Englisch steht – sonst aus den
deutschen Namen.

Sammel-Updates laufen nacheinander: Ultimate Updater antwortet, sobald ein Job *gestartet* ist, daher wartet die
Integration, bis der Job eines Systems fertig ist, bevor sie das nächste startet. Solange ein Job läuft, werden
weitere Aktionen abgelehnt.

## Optionen

| Option | Beschreibung |
|---|---|
| Vollständige Statusaktualisierung | Intervall zum Lesen aller Systeme (Standard 60 min). Nach einem Job oder einer Aktion wird der Status sofort gelesen. |
| Job-Abfrage | Wie oft die Jobliste gelesen wird: im Leerlauf (Standard 30 s) und während ein Job läuft (Standard 2 s) |
| Von Sammel-Updates ausgenommen | VMs/CTs, die die Sammel-Update-Buttons überspringen (z. B. die Home-Assistant-VM selbst) |
| Sammel-Updates umfassen | **Nur laufende VMs/CTs** (Standard) oder **alle VMs/CTs** – „alle“ braucht `STOPPED_CONTAINER` / `STOPPED_VM` in der `update.conf` von Ultimate Updater |
| Neustart-Buttons erlauben | Standardmäßig aus |
| Nicht mehr vorhandene Systeme entfernen | Entfernt die Geräte von Systemen, die Ultimate Updater nicht mehr meldet (standardmäßig an). Sonst bleiben sie nicht verfügbar und lassen sich auf der Geräteseite löschen. |

## Automationsbeispiel

Benachrichtigung bei fehlgeschlagenem Job (die möglichen `event_type`-Werte stehen im Attribut `event_types` der Event-Entität):

```yaml
alias: Ultimate Updater Job fehlgeschlagen
mode: queued
triggers:
  - trigger: event.received
    target:
      entity_id: event.ultimate_updater_job_finished
    options:
      event_type:
        - failed
        - interrupted
actions:
  - action: notify.notify
    data:
      title: "Update-Job {{ trigger.to_state.attributes.event_type }}"
      message: "{{ trigger.to_state.attributes.target_name }}: {{ trigger.to_state.attributes.log or '' }}"
```

Auf Home-Assistant-Versionen ohne den Trigger `event.received` stattdessen einen `state`-Trigger auf die
Event-Entität und eine `state`-Bedingung auf ihr Attribut `event_type` verwenden.

## Sicherheit

- Das API-Token erlaubt keinen Proxmox-Login, funktioniert nur über HTTPS und hat genau die Berechtigungen, die du
  vergibst. Widerrufen auf dem Host mit `ultimate-updater-api-token revoke <id>`.
- Das TLS-Zertifikat wird standardmäßig **nicht geprüft** (selbstsigniertes Proxmox-Zertifikat). *TLS-Zertifikat
  prüfen* aktivieren, wenn die Web-UI ein vertrauenswürdiges Zertifikat hat, und nur in einem vertrauenswürdigen
  Netz betreiben.
- Diagnosedaten enthalten den Status deiner Systeme, aber nicht das Token.

## Entwicklung

```bash
pip install -r requirements_test.txt
pytest
```
