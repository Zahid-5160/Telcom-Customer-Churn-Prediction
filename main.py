"""Command line entry point for the churn project.

    python main.py build     # analyse the data and train the model
    python main.py serve     # start the dashboard
    python main.py train     # train only
    python main.py analyse   # exploratory analysis only
    python main.py predict   # score one example customer from the terminal
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser

from churn.config import INSIGHTS_FILE, METRICS_FILE, MODEL_FILE, RAW_DATA_FILE

BANNER = r"""
  ____ _                      ___           _       _     _
 / ___| |__  _   _ _ __ _ __ |_ _|_ __  ___(_) __ _| |__ | |_
| |   | '_ \| | | | '__| '_ \ | || '_ \/ __| |/ _` | '_ \| __|
| |___| | | | |_| | |  | | | || || | | \__ \ | (_| | | | | |_
 \____|_| |_|\__,_|_|  |_| |_|___|_| |_|___/_|\__, |_| |_|\__|
                                              |___/
  Telco Customer Churn - prediction, explanation and retention
"""


def cmd_analyse(_args) -> int:
    from churn.insights import build

    print("\n[1/1] Exploring the data ...")
    build()
    return 0


def cmd_train(_args) -> int:
    from churn.train import train

    print("\n[1/1] Training and comparing models ...")
    train()
    return 0


def cmd_build(args) -> int:
    print(BANNER)
    print("[1/2] Exploring the data ...")
    from churn.insights import build

    build()

    print("\n[2/2] Training and comparing models ...")
    from churn.train import train

    train()

    print("\nDone. Start the dashboard with:  python main.py serve")
    return 0


def cmd_predict(args) -> int:
    from churn.predictor import predict

    customer = {
        "gender": "Female", "SeniorCitizen": "No", "Partner": "No", "Dependents": "No",
        "tenure": args.tenure, "PhoneService": "Yes", "MultipleLines": "No",
        "InternetService": "Fiber optic", "OnlineSecurity": "No", "OnlineBackup": "No",
        "DeviceProtection": "No", "TechSupport": "No", "StreamingTV": "Yes",
        "StreamingMovies": "Yes", "Contract": args.contract, "PaperlessBilling": "Yes",
        "PaymentMethod": "Electronic check", "MonthlyCharges": args.monthly,
        "TotalCharges": round(args.monthly * args.tenure, 2),
    }
    result = predict(customer)
    print(json.dumps(result, indent=2))
    return 0


def artifacts_are_stale() -> bool:
    """True when the model or the analysis needs rebuilding.

    Either the files are missing, or the dataset has been edited since they were
    generated - in which case the dashboard would be showing yesterday's numbers.
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

    uvicorn.run(
        "churn.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Telco customer churn - analysis, model and dashboard.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("analyse", help="run the exploratory analysis").set_defaults(
        func=cmd_analyse
    )
    subparsers.add_parser("train", help="train and compare the models").set_defaults(
        func=cmd_train
    )
    subparsers.add_parser("build", help="analyse then train (full pipeline)").set_defaults(
        func=cmd_build
    )

    serve = subparsers.add_parser("serve", help="start the web dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    serve.add_argument("--no-browser", action="store_true", help="do not open a browser")
    serve.set_defaults(func=cmd_serve)

    predict = subparsers.add_parser("predict", help="score one example customer")
    predict.add_argument("--tenure", type=int, default=3)
    predict.add_argument("--monthly", type=float, default=95.0)
    predict.add_argument("--contract", default="Month-to-month")
    predict.set_defaults(func=cmd_predict)

    return parser


def main(argv: list[str] | None = None) -> int:
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
