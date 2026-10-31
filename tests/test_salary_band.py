"""Tests for tools/salary_band.py - the salary band /scrape shows with the figure to state.

The suggested figure is what goes into the form, so the rules that matter are
never above the band's top, never below the floor. The text cases come from
real postings (shortened).
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import salary_band as sb  # noqa: E402

# The cases below were written against a EUR 75,000 floor.
sb.FLOOR = 75_000


def band(text):
    found = sb.find_bands(text)
    return (found[0]["min"], found[0]["max"]) if found else None


class FindBands(unittest.TestCase):
    def test_reads_the_common_formats(self):
        cases = {
            "Gehalt: 63.000-75.000 Euro, Wochenstunden: 40": (63000, 75000),
            "What we offer - €52,000-€60,320 gross per annum based on 40 hours per week": (52000, 60320),
            "Salary range: €65k – €85k": (65000, 85000),
            "Gehalt: 65-85k je nach Erfahrung": (65000, 85000),
            "Vergütung 55 – 70 T€ brutto": (55000, 70000),
            "Jahresgehalt zwischen 78.308 € bis 97.040 €": (78308, 97040),
            "Gehalt: 65 - 85.000 € brutto": (65000, 85000),
        }
        for text, expected in cases.items():
            self.assertEqual(band(text), expected, text)

    def test_monthly_figures_become_yearly(self):
        found = sb.find_bands("Wir zahlen zwischen 4.500 und 6.000 Euro monatlich")
        self.assertEqual((found[0]["min"], found[0]["max"], found[0]["period"]), (54000, 72000, "month"))

    def test_figures_that_are_not_pay_are_ignored(self):
        for text in ["Umsatz 50 - 100 Mio. €", "Stundensatz 80 - 95 €/h",
                     "200 - 500 Mitarbeitende, Gehalt nach Vereinbarung", "Projekt 2025 – 2026 im Team",
                     "650,000 active developers and 190K+ GitHub stars"]:
            self.assertEqual(sb.find_bands(text), [], text)


class Suggest(unittest.TestCase):
    def test_sits_seventy_percent_up_the_band(self):
        self.assertEqual(sb.suggest({"min": 65000, "max": 85000}), 79000)
        self.assertEqual(sb.suggest({"min": 72000, "max": 92000}), 86000)

    def test_never_above_the_top_never_below_the_floor(self):
        self.assertEqual(sb.suggest({"min": 63000, "max": 75000}), 75000)
        self.assertEqual(sb.suggest({"min": 60000, "max": 80000}), 75000)
        self.assertLessEqual(sb.suggest({"min": 84000, "max": 85000}), 85000)

    def test_a_band_below_the_floor_gets_no_figure(self):
        self.assertIsNone(sb.suggest({"min": 55000, "max": 70000}))
        self.assertEqual(sb.suggest({"min": 55000, "max": 70000}, floor=65000), 66000)


class Assess(unittest.TestCase):
    def test_label_shows_band_and_figure(self):
        self.assertEqual(sb.assess("Gehalt: 65.000 bis 85.000 EUR")["label"], "65k–85k → 79k")
        self.assertEqual(sb.assess("Gehalt: 55.000 bis 65.000 EUR")["label"], "55k–65k ⚠ unter 75k")

    def test_the_highest_of_several_bands_is_the_target(self):
        a = sb.assess("Junior: 45.000 - 55.000 €, Senior: 70.000 - 90.000 €")
        self.assertEqual((a["band"]["min"], a["wish"], a["bands"]), (70000, 84000, 2))

    def test_single_figures_get_no_figure(self):
        for text, expected in [("Jahresbruttogehalt von bis zu 85.000 €", "bis 85k"),
                               ("Jahreszielgehalt ab 70.000 € brutto", "ab 70k"),
                               ("Compensation: 100,000 Euros", "100k genannt")]:
            a = sb.assess(text)
            self.assertEqual((a["label"], a["wish"]), (expected, None), text)

    def test_no_pay_no_label(self):
        self.assertEqual(sb.assess("Flache Hierarchien und ein tolles Team.")["label"], "")


class PortalField(unittest.TestCase):
    """The band XING, Workwise, freehire and the Arbeitsagentur show in their UI."""

    def test_the_portal_field_wins_over_the_text(self):
        a = sb.assess("Gehalt: 50.000 - 60.000 €", portal_salary="65000–85000 €", portal="workwise-search")
        self.assertEqual((a["source"], a["label"]), ("portal", "65k–85k → 79k"))

    def test_each_portal_format(self):
        cases = {"62.000 € – 85.000 €": (62000, 85000), "65000–85000 €": (65000, 85000),
                 "€70,000.00/yr - €90,000.00/yr": (70000, 90000),
                 "50000–80000 € (StepStone-Schätzung)": (50000, 80000),
                 "4500–5500 € monatlich": (54000, 66000),
                 "EUR 90000–120000/year": (90000, 120000),
                 "4200–5100 EUR (Monatsgehalt)": (50400, 61200)}
        for field, expected in cases.items():
            found = sb.portal_bands(field)
            self.assertEqual((found[0]["min"], found[0]["max"]), expected, field)

    def test_a_xing_forecast_is_marked_and_an_employer_band_is_not(self):
        a = sb.assess("", portal_salary="48500–66000 € (XING-Schätzung)", portal="xing-search")
        self.assertEqual((a["estimate"], a["label"]), (True, "48.5k–66k ⚠ unter 75k (XING-Schätzung)"))
        a = sb.assess("", portal_salary="75000–95000 €", portal="xing-search")
        self.assertEqual((a["estimate"], a["label"]), (False, "75k–95k → 89k"))

    def test_a_stepstone_estimate_says_so(self):
        a = sb.assess("", portal_salary="50000–80000 € (StepStone-Schätzung)", portal="stepstone-search")
        self.assertEqual((a["estimate"], a["label"]), (True, "50k–80k → 75k (StepStone-Schätzung)"))

    def test_hourly_rates_are_not_a_salary(self):
        self.assertEqual(sb.portal_bands("$80.00/hr - $120.00/hr"), [])

    def test_an_unreadable_portal_field_falls_back_to_the_text(self):
        a = sb.assess("Gehalt: 65.000 - 85.000 €", portal_salary="Nach Vereinbarung", portal="arbeitsagentur-search")
        self.assertEqual((a["source"], a["wish"]), ("text", 79000))


if __name__ == "__main__":
    unittest.main()
