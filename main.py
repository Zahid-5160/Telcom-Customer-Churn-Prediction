"""Command line entry point for Retain.

    python main.py build      # analyse the data and train the model
    python main.py serve      # start the dashboard
    python main.py shortcut   # put a desktop shortcut on this computer
    python main.py train      # train only
    python main.py analyse    # workforce analysis only
    python main.py predict    # score one example employee from the terminal
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser

from retain.config import INSIGHTS_FILE, METRICS_FILE, MODEL_FILE, RAW_DATA_FILE
from retain.console import enable_unicode

BANNER = r"""
  ____      _        _
 |  _ \ ___| |_ __ _(_)_ __
 | |_) / _ \ __/ _` | | '_ \
 |  _ <  __/ || (_| | | | | |
 |_| \_\___|\__\__,_|_|_| |_|

  Employee retention intelligence - predict, explain, act
"""


def cmd_analyse(_args) -> int:
    from retain.insights import build

    print("\n[1/1] Analysing the workforce ...")
    build()
    return 0


def cmd_train(_args) -> int:
    from retain.train import train

    print("\n[1/1] Training and comparing models ...")
    train()
    return 0


def cmd_build(_args) -> int:
    print(BANNER)
    print("[1/2] Analysing the workforce ...")
    from retain.insights import build

    build()

    print("\n[2/2] Training and comparing models ...")
    from retain.train import train

    train()

    print("\nDone. Start the dashboard with:  python main.py serve")
    return 0


def cmd_predict(args) -> int:
    from retain.predictor import predict

    employee = {
        "Department": "Research and Development", "JobRole": "Laboratory Technician",
        "JobLevel": "Entry", "BusinessTravel": "Rare", "OverTime": args.overtime,
        "MaritalStatus": "Single", "StockOptionLevel": "None", "JobSatisfaction": "Low",
        "EnvironmentSatisfaction": "Medium", "WorkLifeBalance": "High",
        "JobInvolvement": "High", "PerformanceRating": "Meets expectations",
        "Age": args.age, "MonthlyIncome": args.salary, "DistanceFromHome": 10,
        "PercentSalaryHike": 12, "TrainingTimesLastYear": 2, "NumCompaniesWorked": 1,
        "TotalWorkingYears": max(args.years, 1), "YearsAtCompany": args.years,
        "YearsInCurrentRole": max(args.years - 1, 0), "YearsSinceLastPromotion": args.years,
    }
    print(json.dumps(predict(employee), indent=2))
    return 0


def cmd_shortcut(_args) -> int:
    from scripts.make_shortcut import create

    return 0 if create() else 1


def artifacts_are_stale() -> bool:
    """True when the model or the analysis needs rebuilding.

    Either the files are missing, or the dataset has been edited since they were
    generated - in which case the dashboard would show yesterday's numbers.
    """
    outputs = [MODEL_FILE, METRICS_FILE, INSIGHTS_FILE]
    if any(not path.exists() for path in outputs):
        return True
    if not RAW_DATA_FILE.exists():
        return False
    newest_data = RAW_DATA_FILE.stat().st_mtime
    return any(path.stat().st_mtime < newest_data for path in outputs)


def cmd_serve(args) -> int:
    import uvicorn

    if artifacts_are_stale():
        print("Model or analysis missing or out of date - building them first.\n")
        cmd_build(args)

    url = f"http://{args.host}:{args.port}"
    print(BANNER)
    print(f"  Dashboard : {url}")
    print(f"  API docs  : {url}/docs")
    print("\n  Press CTRL+C to stop.\n")

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run("retain.api:app", host=args.host, port=args.port,
                reload=args.reload, log_level="warning")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Retain - employee retention analysis, model and dashboard.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("analyse", help="run the workforce analysis").set_defaults(
        func=cmd_analyse
    )
    subparsers.add_parser("train", help="train and compare the models").set_defaults(
        func=cmd_train
    )
    subparsers.add_parser("build", help="analyse then train (full pipeline)").set_defaults(
        func=cmd_build
    )
    subparsers.add_parser(
        "shortcut", help="create a desktop shortcut that opens the dashboard"
    ).set_defaults(func=cmd_shortcut)

    serve = subparsers.add_parser("serve", help="start the web dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    serve.add_argument("--no-browser", action="store_true", help="do not open a browser")
    serve.set_defaults(func=cmd_serve)

    predict = subparsers.add_parser("predict", help="score one example employee")
    predict.add_argument("--age", type=int, default=28)
    predict.add_argument("--salary", type=float, default=45000)
    predict.add_argument("--years", type=int, default=2)
    predict.add_argument("--overtime", default="Yes", choices=["Yes", "No"])
    predict.set_defaults(func=cmd_predict)

    return parser


def main(argv: list[str] | None = None) -> int:
    enable_unicode()  # the rupee sign needs a UTF-8 console
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args = parser.parse_args(["serve"])
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
