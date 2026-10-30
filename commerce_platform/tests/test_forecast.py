"""Meaningful forecasting invariants; no network or source download required."""
import csv
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

# Load the sibling module explicitly so tests also work from another cwd.
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("commerce_forecast", ROOT / "forecast.py")
forecast = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = forecast
spec.loader.exec_module(forecast)


def sample_months():
    return [forecast.Month(month=month, gross_pence=index * 100, cancel_pence=0,
                           net_pence=index * 100, orders=index)
            for index, month in enumerate(forecast.EXPECTED_MONTHS, 1)]


class ForecastTests(unittest.TestCase):
    def test_baselines_use_correct_lags_and_round_to_pence(self):
        self.assertEqual(forecast.predict("last_month", [100, 201, 300]), 300)
        self.assertEqual(forecast.predict("mean_3", [9999, 100, 201, 300]), 200)
        self.assertEqual(forecast.predict("mean_3", [100, 202, 300]), 201)
        self.assertEqual(forecast.predict("seasonal_12", list(range(24))), 12)
        with self.assertRaises(ValueError):
            forecast.predict("seasonal_12", [100] * 11)

    def test_expanding_backtest_matches_hand_calculation(self):
        result = forecast.build_report(sample_months())
        self.assertEqual([fold["month"] for fold in result["backtest"]],
                         ["2011-06", "2011-07", "2011-08", "2011-09", "2011-10", "2011-11"])
        self.assertEqual([fold["train_months"] for fold in result["backtest"]], [18, 19, 20, 21, 22, 23])
        models = {model["id"]: model for model in result["models"]}
        self.assertEqual(models["last_month"]["mae_gbp"], 1)
        self.assertEqual(models["mean_3"]["mae_gbp"], 2)
        self.assertEqual(models["seasonal_12"]["mae_gbp"], 12)
        self.assertEqual(models["last_month"]["forecast_gbp"], 24)
        self.assertEqual(models["mean_3"]["forecast_gbp"], 23)
        self.assertEqual(models["seasonal_12"]["forecast_gbp"], 13)
        self.assertEqual(result["backtest"][0]["errors_gbp"]["seasonal_12"], 12)

    def test_future_changes_cannot_leak_into_earlier_predictions(self):
        rows = sample_months()
        original = forecast.build_report(rows)
        rows[21:] = [replace(row, gross_pence=99999999, net_pence=99999999) for row in rows[21:]]
        changed = forecast.build_report(rows)
        # September's prediction must also remain unchanged: September is not in its training prefix.
        for before, after in zip(original["backtest"][:4], changed["backtest"][:4]):
            self.assertEqual(before["predictions"], after["predictions"])
        self.assertNotEqual(original["backtest"][-1]["predictions"]["last_month"],
                            changed["backtest"][-1]["predictions"]["last_month"])

    def test_wape_uses_absolute_actual_denominator(self):
        metrics = forecast.score([100, -100], [0, 0])
        self.assertEqual(metrics["mae_gbp"], 1)
        self.assertEqual(metrics["wape"], 1)
        self.assertEqual(metrics["wape_denominator_pence"], 200)
        self.assertIsNone(forecast.score([0, 0], [100, 0])["wape"])

    def test_selection_ties_and_limits_are_explicit(self):
        rows = [replace(row, gross_pence=100, net_pence=100) for row in sample_months()]
        result = forecast.build_report(rows)
        self.assertEqual(result["recommended_id"], "last_month")
        self.assertTrue(result["selection"]["same_folds_used_for_selection"])
        self.assertFalse(result["selection"]["independent_selected_model_evaluation"])
        self.assertEqual(result["forecast_month"], "2011-12")
        self.assertTrue(all("interval" not in model for model in result["models"]))

    def read_fixture(self, rows):
        with tempfile.TemporaryDirectory(prefix="forecast-test-") as directory:
            path = Path(directory) / "monthly.csv"
            with path.open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=forecast.FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            return forecast.read_monthly(path)

    def dictionaries(self):
        return [vars(row).copy() for row in sample_months()]

    def test_input_rejects_missing_duplicate_and_partial_december(self):
        rows = self.dictionaries()
        for invalid in [rows[:-1], rows + [rows[0]], rows + [{**rows[-1], "month": "2011-12"}]]:
            with self.subTest(months=len(invalid)), self.assertRaises(ValueError):
                self.read_fixture(invalid)

    def test_input_rejects_malformed_and_inconsistent_money(self):
        for changes in [{"net_pence": "1.5"}, {"net_pence": ""}, {"gross_pence": -1},
                        {"cancel_pence": -1}, {"net_pence": 999}, {"month": "2010-1"}, {"month": "2010-13"}]:
            rows = self.dictionaries()
            rows[0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.read_fixture(rows)

    def test_cancellation_only_month_is_negative_not_missing(self):
        rows = self.dictionaries()
        rows[0].update(gross_pence=0, cancel_pence=20574, net_pence=-20574, orders=0)
        parsed = self.read_fixture(list(reversed(rows)))
        self.assertEqual(parsed[0].net_pence, -20574)
        self.assertEqual(parsed[0].orders, 0)


if __name__ == "__main__":
    unittest.main()
