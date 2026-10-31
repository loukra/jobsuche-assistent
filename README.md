# Jobsuche-Assistent

Claude durchsucht die deutschen Jobportale nach neuen Stellen, sortiert sie danach, wie gut sie zu dir passen, hilft dir beim Anschreiben und führt Buch über deine Bewerbungen. Alles läuft auf deinem Rechner, mit deinem eigenen Claude-Abo.

**Was du brauchst:** ein Claude-Abo (mindestens Pro) und die [Claude Desktop-App](https://claude.com/download). Kein GitHub-Konto, kein Terminal-Wissen.

**Was es kann:**

- sucht auf Arbeitsagentur, StepStone, XING, LinkedIn, freehire, Workwise und Instaffo, vollständig und nicht nur die erste Seite
- bewertet neue Stellen nach deinem Profil und zeigt Gehaltsbänder samt Betrag für den Gehaltswunsch
- unterstützt dich bei den Anschreiben
- führt deine Bewerbungen, bereitet Vorstellungsgespräche vor und zeigt eine Übersicht

## Einrichtung

Die Einrichtung dauert beim ersten Mal etwa eine halbe Stunde. Du brauchst dafür nichts zu tippen, Claude macht es.

**Schritt 1: Projekt holen.** Öffne die Claude-App, wechsle zu **Code** und starte eine Sitzung in einem leeren Ordner, zum Beispiel `Dokumente/Start`. Schreibe dort:

> Klone https://github.com/loukra/jobsuche-assistent.git in den Ordner `Jobsuche` neben diesem. Entferne danach im Ordner `Jobsuche` mit `git remote remove origin` die Verbindung zum Projekt, damit meine persönlichen Daten später nirgends hochgeladen werden können. Installiere dann alles, was laut `ANLEITUNG.md` Abschnitt 1.2 noch fehlt, und frage vor jeder Installation nach.

**Schritt 2: Ordner öffnen.** Starte eine neue Sitzung in `Jobsuche` (Code → Ordner wählen) und bestätige, dass du dem Ordner vertraust.

**Schritt 3: Profil anlegen.** Lege deinen Lebenslauf in `documents/cv/` und tippe `/setup`.

Der ganze weitere Ablauf steht in der **[ANLEITUNG.md](ANLEITUNG.md)**.

## Wichtig zu wissen

- **Deine Daten bleiben bei dir.** Lebenslauf, Anschreiben, Stellenliste und Bewerbungen liegen nur im Ordner auf deinem Rechner. Das Profil, das `/setup` in `CLAUDE.md` und die Profildateien schreibt, enthält persönliche Daten: Wenn du den Ordner jemals mit git hochlädst, dann nur in ein **privates** Repository.
- **Portale nur zum persönlichen Gebrauch.** Die Suche liest öffentliche Seiten, teils inoffizielle Schnittstellen. Nutze sie mit wenig Volumen und für dich allein, so wie bei einem Besuch im Browser. Einige Portale verbieten automatisierten Zugriff in ihren Bedingungen.
- **Das Kontingent.** `/scrape` verbraucht am meisten, weil Claude Anzeigen liest. Die Obergrenze steht im Suchprofil (`auto_read_max`), mehr dazu in der Anleitung.

## Herkunft und Lizenz

Dieses Projekt ist eine deutsche Ausgabe von [ai-job-search](https://github.com/MadsLorentzen/ai-job-search) von Mads Lorentzen (MIT-Lizenz, siehe [LICENSE](LICENSE)), erweitert um deutsche Portale, einen vollständigen Sweep mit Suchprofil und eine deutsche Anleitung. Es ist ein unabhängiges Projekt und steht in keiner Verbindung zu Anthropic. Claude und Claude Code sind Marken von Anthropic.

## Für Entwickler

```bash
python3 -m pytest                                   # Python-Tests
for cli in .agents/skills/*/cli; do (cd "$cli" && bun install && bun test); done   # Portal-Werkzeuge
```

Weitere Details in [SETUP.md](SETUP.md) und [CONTRIBUTING.md](CONTRIBUTING.md).
