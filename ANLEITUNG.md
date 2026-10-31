# Anleitung: Jobsuche mit Claude

Dieser Ordner ist deine Jobsuche. Claude sucht jeden Tag neue Stellen auf den deutschen Jobportalen, sortiert sie danach, wie gut sie zu dir passen, schreibt Anschreiben in deinem Ton und führt Buch über deine Bewerbungen. Alles läuft auf deinem Rechner, deine Daten bleiben bei dir.

Du brauchst dafür kein GitHub und kein Terminal-Wissen. Die Einrichtung macht man einmal, am besten zusammen mit jemandem, der sie schon kennt. Danach redest du nur noch mit Claude.

---

## Überblick: die Befehle

Du tippst die Befehle in den Chat der Claude-App. Mehr musst du dir nicht merken.

| Befehl | Was passiert |
|---|---|
| `/setup` | Einmalig: Claude liest deinen Lebenslauf, stellt Fragen und legt dein Profil und deine Suche an |
| `/scrape` | Neue Stellen von den Portalen holen und bewerten |
| `/coverletter <Firma oder Link>` | Das Anschreiben für eine Stelle schreiben |
| `/outcome <Firma>` | Festhalten, was aus einer Bewerbung geworden ist (abgeschickt, Einladung, Absage …); Claude fragt nach |
| `/interview <Firma>` | Vorbereitung auf ein Vorstellungsgespräch |
| `/html-report` | Übersicht über alle Bewerbungen als Seite mit Diagrammen |

Daneben kannst du Claude jederzeit ganz normal schreiben, zum Beispiel „Die Suche findet zu viele Vertriebsjobs“ oder „Schreib den zweiten Absatz weniger förmlich“.

In der Befehlsliste der App tauchen noch weitere Befehle auf (`/rank`, `/apply`, `/expand` …). Die stammen aus dem Original-Framework und werden für diesen Ablauf nicht gebraucht.

---

## 1. Einmalige Einrichtung

### 1.1 Claude

1. Ein **Claude-Abo** abschließen (mindestens Pro) auf claude.ai.
2. Die **Claude Desktop-App** installieren und mit dem Abo anmelden.
3. In der App den Bereich **Code** öffnen. Dort arbeitet Claude mit den Dateien in einem Ordner.

### 1.2 Werkzeuge (einmal, ca. 15 Minuten)

Diese Programme braucht Claude im Hintergrund. Claude installiert sie für dich und fragt vor jeder Installation nach. Die Einrichtung des Ordners (Schritt 1.3) enthält den Auftrag dafür schon.

- **Git** (holt das Projekt). Auf dem Mac fragt macOS beim ersten Mal von selbst nach den Entwicklerwerkzeugen, einfach bestätigen. Unter Windows wird [Git for Windows](https://git-scm.com/download/win) gebraucht.
- **Python 3** mit dem Paket `pypdf` (prüft die fertigen PDFs)
- **Bun** (führt die Portal-Suchen aus): `curl -fsSL https://bun.sh/install | bash`
- **LaTeX** (baut Lebenslauf und Anschreiben als PDF). Auf dem Mac am einfachsten TinyTeX, die genauen Befehle stehen in `SETUP.md` unter „Minimal TeX install“.
- **Portal-Werkzeuge** im Ordner einmal installieren:
  ```bash
  for cli in .agents/skills/*/cli; do (cd "$cli" && bun install); done
  ```

Unter Windows gilt dasselbe, die Befehle für PowerShell stehen in `SETUP.md`.

### 1.3 Den Ordner holen und öffnen

1. In der Claude-App unter **Code** eine Sitzung in einem leeren Ordner starten (zum Beispiel `Dokumente/Start`) und Claude den Auftrag aus dem [README](README.md) geben („Klone … in den Ordner `Jobsuche` …“). Claude holt das Projekt, entfernt die Verbindung zum öffentlichen Repository (damit deine persönlichen Daten später nirgends hochgeladen werden können) und installiert, was laut 1.2 fehlt.
2. Danach in der App eine **neue** Sitzung starten und den Ordner `Jobsuche` auswählen. Die Befehle wie `/setup` gibt es erst in einer Sitzung, die in diesem Ordner gestartet wurde.
3. Beim ersten Öffnen fragt Claude, ob du diesem Ordner vertraust. Bestätige das (**„Ja, ich vertraue diesem Ordner“**). Ohne diese Bestätigung ignoriert Claude die mitgelieferten Erlaubnisregeln und fragt bei jedem Schritt einzeln nach.

Ab jetzt öffnest du für die Jobsuche immer den Ordner `Jobsuche`.

---

## 2. Dein Profil anlegen: `/setup`

1. Lege deine Unterlagen in den Ordner `documents/`:
   - Lebenslauf (PDF oder Word) nach `documents/cv/`
   - Zeugnisse und Empfehlungsschreiben nach `documents/references/`
   - optional: LinkedIn-Export nach `documents/linkedin/`, Abschlusszeugnisse nach `documents/diplomas/`
2. Tippe `/setup` und sage „go“, wenn Claude fragt.
3. Claude liest alles, zeigt dir, was es verstanden hat, und fragt nach, wo etwas fehlt oder sich widerspricht. Antworte so genau wie möglich: Alles, was hier steht, nutzt Claude später für Bewertungen und Anschreiben. **Claude erfindet nichts dazu**, was nicht im Profil steht, kommt auch in kein Anschreiben.
4. Zum Schluss legt Claude dein **Suchprofil** an (`job_scraper/sweep_profile.json`): wo du suchst und in welchem Umkreis, ob auch Remote-Stellen, nach welchen Berufsbezeichnungen und welche Stellen nach oben oder unten sortiert werden. Schau dir die Liste an, die Claude dir zeigt, und sag, was fehlt.

Das dauert beim ersten Mal 20 bis 40 Minuten. Du kannst `/setup` später jederzeit noch einmal laufen lassen.

---

## 3. Der tägliche Ablauf

### Schritt 1: Neue Stellen holen – `/scrape`

Claude durchsucht alle Portale (Arbeitsagentur, StepStone, XING, LinkedIn, freehire, Workwise, Instaffo) nach allem, was seit dem letzten Mal neu ist, und zwar vollständig, nicht nur die erste Seite. Danach liest Claude die vielversprechendsten Anzeigen ganz und bewertet sie.

Am Ende bekommst du eine Tabelle: Passung (hoch, mittel), Titel, Firma, Ort, Gehalt (mit dem Betrag, den du als Gehaltswunsch angeben könntest, wenn die Anzeige eine Spanne nennt), Frist und Link.

- Dauer: je nach Suchgebiet 5 bis 30 Minuten, mit Remote-Suche in ganz Deutschland eher länger. Du musst nicht danebensitzen.
- Am besten einmal am Tag. Fällt ein Tag aus, holt der nächste Lauf ihn automatisch nach.
- Jede Stelle wird gemerkt und taucht nicht noch einmal als neu auf.
- **Der allererste Lauf** merkt sich alle älteren Anzeigen und solche ohne Datum nur, ohne sie zu lesen. Sonst wäre am ersten Tag das ganze Portal „neu“. Ab dem zweiten Lauf siehst du nur noch wirklich Neues.
- Claude liest pro Lauf höchstens 50 Anzeigen ganz (einstellbar, siehe Abschnitt 5), dazu eine Stichprobe von rund 10 bis 15 weiteren, die niedrig bewertet wurden. Die Stichprobe zeigt, ob die Suche gute Stellen übersieht, und sagt dir das im Bericht. Alle anderen stehen trotzdem in der Titelliste, und du kannst sagen „lies Nummer 812 und 1033 auch“.

### Schritt 2: Anschreiben – `/coverletter`

```
/coverletter <Link zur Anzeige>
```

Claude liest die Anzeige, prüft, was dein Lebenslauf schon zeigt und was nicht, und schreibt ein Anschreiben, das genau diese Lücke füllt, statt den Lebenslauf zu wiederholen. Firmenangaben prüft Claude vorher im Netz. Am Ende bekommst du das Anschreiben als PDF und eine Liste der Sätze, bei denen du entscheiden sollst, ob sie stimmen (behalten, abschwächen, streichen). Deinen Lebenslauf schickst du unverändert mit, Claude kennt ihn aus `/setup`.

**Lies das Anschreiben immer selbst.** Wenn dir ein Satz nicht gefällt, sag es direkt, am besten mit dem Grund („klingt gestelzt“, „das würde ich so nie sagen“, „zu viel Lebenslauf“). Claude schreibt den Satz um **und merkt sich die Regel dahinter** für alle künftigen Anschreiben. So werden die Briefe mit jeder Bewerbung besser und immer mehr zu deinen.

Die fertigen Anschreiben liegen in `cover_letters/`.

### Schritt 3: Abschicken und festhalten – `/outcome`

Abschicken machst du selbst, über das Portal oder per Mail. Danach:

```
/outcome <Firma>
```

Claude fragt, was passiert ist, und du antwortest einfach: „abgeschickt“, später „Einladung zum Gespräch am …“, „Absage“ oder „keine Antwort“. Ohne Firmennamen zeigt `/outcome` alle offenen Bewerbungen. Claude führt die Liste `job_search_tracker.csv`, und `/outcome followup` schlägt Nachfass-Mails für Bewerbungen vor, bei denen sich seit zehn Tagen nichts getan hat.

### Schritt 4: Gespräch vorbereiten – `/interview`

```
/interview <Firma>
```

Claude bereitet wahrscheinliche Fragen, deine Beispiele aus dem Profil und eigene Fragen an die Firma vor.

### Zwischendurch: Überblick – `/html-report`

Erzeugt eine Übersichtsseite: wie viele Bewerbungen, in welchem Stand, wie viele Gespräche.

---

## 4. Nachjustieren

Am Anfang passt noch nicht alles. Das ist normal: Die Suche und die Anschreiben werden besser, je mehr du Claude sagst, was nicht stimmt. Sag es einfach im Chat:

| Du merkst … | Sag zum Beispiel … | Claude ändert … |
|---|---|---|
| Zu viele unpassende Stellen | „Ich will keine Vertriebs- oder Teamleiter-Stellen sehen“ | die Gewichte im Suchprofil |
| Gute Stellen fehlen | „Stellen als ‚Produktmanagerin‘ fehlen, die will ich auch sehen“ | die Suchbegriffe im Suchprofil |
| Anderer Ort oder Umkreis | „Such auch in Hannover, 30 km“ | die Suchgebiete |
| Fakt fehlt oder ist falsch | „Ich habe 2022 noch ein Zertifikat in X gemacht“ | dein Profil |
| Satz im Anschreiben gefällt nicht | „So rede ich nicht, schreib es einfacher“ | das Anschreiben und die Lektionen |

Wo die Dinge liegen, falls du nachsehen willst:

| Datei | Inhalt |
|---|---|
| `CLAUDE.md` | Kurzprofil, Wünsche, Ausschlusskriterien |
| `.claude/skills/job-application-assistant/01-candidate-profile.md` | dein ausführliches Profil |
| `job_scraper/sweep_profile.json` | deine Suche: Orte, Remote, Suchbegriffe, Gewichte |
| `.claude/commands/coverletter.md` | Regeln und Lektionen für Anschreiben |
| `job_search_tracker.csv` | alle Bewerbungen |

---

## 5. Gut zu wissen

**Kontingent.** Das Claude-Abo hat ein Nutzungslimit. Am meisten verbraucht `/scrape`, weil Claude dabei Anzeigen liest. Wie viele es höchstens pro Lauf sind, steht im Suchprofil als `auto_read_max` (Start: 50). Zur Einordnung: Ein Testlauf mit Hamburg (20 km) plus Remote in ganz Deutschland brachte an einem einzigen Tag über 800 Anzeigen, die die Schwelle fürs automatische Lesen erreichten. Ohne Obergrenze wäre ein Pro-Abo damit sofort aufgebraucht. Wenn das Limit trotzdem oft erreicht wird: Claude bitten, „weniger Anzeigen automatisch zu lesen“, das Suchgebiet enger machen oder ein größeres Abo nehmen. Wenn Kontingent übrig ist, darf die Zahl auch höher.

**Datenschutz.** Alles liegt nur in diesem Ordner auf deinem Rechner. Bewerbungen, Lebensläufe, Anschreiben und die Stellenliste sind so eingestellt, dass sie nicht versehentlich hochgeladen werden, falls der Ordner einmal mit git geteilt wird.

**Anschreiben-Regeln.** Die ersten Regeln in `coverletter.md` stammen aus vielen Überarbeitungsrunden mit einem anderen Nutzer. Sie gelten für Anschreiben allgemein (keine Floskeln, nichts aus der Anzeige abschreiben, nur eine Lücke ehrlich benennen …). Deine eigenen Korrekturen kommen dazu und haben Vorrang.

**Wenn etwas nicht geht.**
- Ein Portal liefert nichts mehr: `/scrape health` prüft alle Portale und sagt, welches kaputt ist. Portale ändern manchmal ihre Seiten, dann muss das Werkzeug angepasst werden.
- Ein PDF lässt sich nicht bauen: Claude die Fehlermeldung zeigen, meistens fehlt ein LaTeX-Paket.
- Sonst: Claude einfach fragen, was los ist.
