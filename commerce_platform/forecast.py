"""Reproducible one-step revenue baselines with a six-month walk-forward backtest.

Run from this directory after run.py creates the monthly mart:
    python forecast.py --input results/monthly.csv
    python forecast.py --tests-only

Only Python's standard library is required. Monetary inputs and predictions use
integer pence. The fixed project window is December 2009 through November 2011;
partial December 2011 must not be included. Model selection uses the same six
backtest months that are displayed: these scores are not an independent estimate
of the selected strategy's future accuracy. No calibrated interval is estimated.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parent
FIELDS = ("month", "gross_pence", "cancel_pence", "net_pence", "orders")
MODEL_SPECS = (
    ("last_month", "Последний месяц"),
    ("mean_3", "Среднее трёх последних месяцев"),
    ("seasonal_12", "Тот же месяц предыдущего года"),
)
EXPECTED_MONTHS = tuple(
    f"{year}-{month:02d}"
    for year in (2009, 2010, 2011)
    for month in range(1, 13)
    if "2009-12" <= f"{year}-{month:02d}" <= "2011-11"
)
BACKTEST_FOLDS = 6


@dataclass(frozen=True)
class Month:
    month: str
    gross_pence: int
    cancel_pence: int
    net_pence: int
    orders: int


def strict_integer(value: str | None, field: str, row: int) -> int:
    if value is None or not re.fullmatch(r"-?\d+", value.strip()):
        raise ValueError(f"Row {row}: {field} must be an integer number of pence/count")
    return int(value)


def read_monthly(path: Path) -> list[Month]:
    """Validate the aggregate contract; never treat missing months as zero sales."""
    result = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"Expected CSV columns in order: {','.join(FIELDS)}")
        for line_number, row in enumerate(reader, 2):
            month = row["month"]
            if month is None or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
                raise ValueError(f"Row {line_number}: invalid YYYY-MM month")
            if None in row:
                raise ValueError(f"Row {line_number}: extra CSV fields")
            values = {field: strict_integer(row[field], field, line_number) for field in FIELDS[1:]}
            if values["gross_pence"] < 0 or values["cancel_pence"] < 0 or values["orders"] < 0:
                raise ValueError(f"Row {line_number}: gross sales, cancellation magnitude and orders must be nonnegative")
            if values["net_pence"] != values["gross_pence"] - values["cancel_pence"]:
                raise ValueError(f"Row {line_number}: net_pence != gross_pence - cancel_pence")
            result.append(Month(month=month, **values))
    result.sort(key=lambda row: row.month)
    months = tuple(row.month for row in result)
    if len(set(months)) != len(months):
        raise ValueError("Duplicate month keys are not allowed")
    if months != EXPECTED_MONTHS:
        raise ValueError("Expected exactly 24 complete months, 2009-12 through 2011-11. "
                         "Exclude partial December 2011; missing months must not be silently filled.")
    return result


def predict(model_id: str, history_pence: list[int]) -> int:
    """Predict the next month from the training prefix only; no fitted parameters."""
    if model_id == "last_month":
        if not history_pence:
            raise ValueError("last_month requires at least one complete month")
        return history_pence[-1]
    if model_id == "mean_3":
        if len(history_pence) < 3:
            raise ValueError("mean_3 requires at least three complete months")
        # Fraction avoids floating-point penny loss; rounding is to nearest penny.
        return round(Fraction(sum(history_pence[-3:]), 3))
    if model_id == "seasonal_12":
        if len(history_pence) < 12:
            raise ValueError("seasonal_12 requires at least twelve complete months")
        return history_pence[-12]
    raise ValueError(f"Unknown model: {model_id}")


def score(actual_pence: list[int], prediction_pence: list[int]) -> dict:
    if not actual_pence or len(actual_pence) != len(prediction_pence):
        raise ValueError("Actuals and predictions must have the same nonzero length")
    total_absolute_error = sum(abs(actual - predicted) for actual, predicted in zip(actual_pence, prediction_pence))
    denominator = sum(abs(actual) for actual in actual_pence)
    return {
        "mae_gbp": round(float(Fraction(total_absolute_error, len(actual_pence) * 100)), 2),
        "wape": total_absolute_error / denominator if denominator else None,
        "absolute_error_pence": total_absolute_error,
        "wape_denominator_pence": denominator,
    }


def build_report(months: list[Month]) -> dict:
    if tuple(row.month for row in months) != EXPECTED_MONTHS:
        raise ValueError("Report requires the ordered, complete project window 2009-12 through 2011-11")
    target_indexes = range(len(months) - BACKTEST_FOLDS, len(months))
    predictions_by_model = {model_id: [] for model_id, _ in MODEL_SPECS}
    actuals, backtest = [], []
    for index in target_indexes:
        training = months[:index]
        history = [row.net_pence for row in training]
        actual = months[index].net_pence
        actuals.append(actual)
        predictions, errors, absolute_errors = {}, {}, {}
        for model_id, _ in MODEL_SPECS:
            prediction = predict(model_id, history)
            predictions_by_model[model_id].append(prediction)
            predictions[model_id] = prediction / 100
            errors[model_id] = (actual - prediction) / 100
            absolute_errors[model_id] = abs(actual - prediction) / 100
        backtest.append({"month": months[index].month, "train_through": training[-1].month,
                         "train_months": len(training), "actual_gbp": actual / 100,
                         "predictions": predictions, "errors_gbp": errors,
                         "absolute_errors_gbp": absolute_errors})
    history = [row.net_pence for row in months]
    models = []
    for model_id, label in MODEL_SPECS:
        metrics = score(actuals, predictions_by_model[model_id])
        models.append({"id": model_id, "label": label, **metrics,
                       "forecast_gbp": predict(model_id, history) / 100})
    # Same fold count for every strategy. Integer total error avoids rounded-MAE ties.
    winner = min(models, key=lambda model: model["absolute_error_pence"])
    return {
        "meta": {"currency": "GBP", "source": "UCI Online Retail II",
                 "source_url": "https://doi.org/10.24432/C5CG6D", "training_start": months[0].month,
                 "training_end": months[-1].month, "history_months": len(months),
                 "backtest_folds": BACKTEST_FOLDS, "horizon_months": 1,
                 "target": "monthly net sales after cancellation lines, not profit"},
        "forecast_month": "2011-12",
        "models": models,
        "backtest": backtest,
        "history": [{"month": row.month, "net_gbp": row.net_pence / 100} for row in months],
        "recommended_id": winner["id"],
        "recommendation_label": "Минимальная MAE на шести месяцах подбора",
        "selection": {"metric": "MAE", "period_start": backtest[0]["month"],
                      "period_end": backtest[-1]["month"], "same_folds_used_for_selection": True,
                      "independent_selected_model_evaluation": False,
                      "tie_break_order": [model_id for model_id, _ in MODEL_SPECS],
                      "explanation": "Стратегия выбрана по тем же шести фолдам, на которых приведены ошибки. "
                                     "Отдельная независимая оценка выбранной стратегии отсутствует."},
        "limitations": [
            "Backtest: июнь–ноябрь 2011, один месяц вперёд. В каждом фолде доступны только предыдущие полные месяцы.",
            "Шесть ошибок дают ограниченную оценку устойчивости; сравнение и выбор выполнены на одних данных.",
            "Прогноз декабря 2011 построен только по данным до ноября. Неполный декабрь не используется ни для обучения, ни как фактическое значение.",
            "Калиброванный прогнозный интервал не рассчитывается; результат является точечным прогнозом.",
            "Не учтены цены, рекламные кампании, ассортимент, запасы и изменения бизнеса. Это простые базовые стратегии.",
            "WAPE = сумма абсолютных ошибок / сумма абсолютных фактических значений; при нулевом знаменателе WAPE отсутствует.",
            "Оборот после отмен не равен прибыли; прогноз не доказывает будущий результат бизнеса.",
        ],
    }


def write_backtest(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=("model_id", "month", "train_through", "train_months",
                                                   "actual_gbp", "prediction_gbp", "error_gbp", "absolute_error_gbp"))
        writer.writeheader()
        for fold in report["backtest"]:
            for model_id, _ in MODEL_SPECS:
                writer.writerow({"model_id": model_id, "month": fold["month"],
                                 "train_through": fold["train_through"], "train_months": fold["train_months"],
                                 "actual_gbp": f'{fold["actual_gbp"]:.2f}',
                                 "prediction_gbp": f'{fold["predictions"][model_id]:.2f}',
                                 "error_gbp": f'{fold["errors_gbp"][model_id]:.2f}',
                                 "absolute_error_gbp": f'{fold["absolute_errors_gbp"][model_id]:.2f}'})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=ROOT / "results/monthly.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "results/forecast.json")
    parser.add_argument("--backtest-output", type=Path, default=ROOT / "results/forecast_backtest.csv")
    parser.add_argument("--tests-only", action="store_true")
    args = parser.parse_args(argv)
    if args.tests_only:
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_forecast.py")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    try:
        months = read_monthly(args.input)
        report = build_report(months)
        report["meta"].update({"built_at_utc": datetime.now(timezone.utc).isoformat(),
                               "monthly_csv_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest()})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        write_backtest(args.backtest_output, report)
    except (OSError, ValueError) as error:
        print(f"Forecast failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"forecast_month": report["forecast_month"], "recommended_id": report["recommended_id"],
                      "models": report["models"], "output": str(args.output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
