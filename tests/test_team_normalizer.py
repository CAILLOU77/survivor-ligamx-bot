from pathlib import Path
import importlib.util
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "team_normalizer.py"
SPEC = importlib.util.spec_from_file_location("team_normalizer", MODULE_PATH)
team_normalizer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = team_normalizer
assert SPEC.loader is not None
SPEC.loader.exec_module(team_normalizer)


class TeamNormalizerTests(unittest.TestCase):
    def test_strip_accents_preserves_base_text(self):
        self.assertEqual(team_normalizer.strip_accents("América Querétaro León"), "America Queretaro Leon")

    def test_clean_team_name_removes_punctuation_and_accents(self):
        self.assertEqual(team_normalizer.clean_team_name("  Club-América, FC  "), "club america fc")

    def test_canonical_team_key_maps_common_aliases(self):
        cases = {
            "América": "america",
            "Club America": "america",
            "Chivas": "guadalajara",
            "Tigres": "tigres uanl",
            "Pumas": "pumas unam",
            "FC Juárez": "juarez",
            "Atlético San Luis": "atletico de san luis",
            "Querétaro FC": "queretaro",
            "Tijuana Xolos de Caliente": "tijuana",
        }

        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(team_normalizer.canonical_team_key(raw), expected)

    def test_display_team_name_uses_visible_canonical_names(self):
        self.assertEqual(team_normalizer.display_team_name("America"), "América")
        self.assertEqual(team_normalizer.display_team_name("Queretaro FC"), "Querétaro")
        self.assertEqual(team_normalizer.display_team_name("Atletico San Luis"), "Atlético de San Luis")

    def test_teams_match_by_aliases(self):
        matches = [
            ("América", "Club America"),
            ("Chivas Guadalajara", "Guadalajara"),
            ("FC Juárez", "Juarez"),
            ("Tijuana Xolos de Caliente", "Tijuana"),
            ("Atlético de San Luis", "San Luis"),
        ]

        for a, b in matches:
            with self.subTest(a=a, b=b):
                self.assertTrue(team_normalizer.teams_match(a, b))

    def test_teams_do_not_match_unrelated_clubs(self):
        self.assertFalse(team_normalizer.teams_match("América", "Atlas"))
        self.assertFalse(team_normalizer.teams_match("Puebla", "Pumas"))


if __name__ == "__main__":
    unittest.main()
