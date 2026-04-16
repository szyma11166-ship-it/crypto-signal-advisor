import json
import os

PORTFOLIO_FILE = "app/portfolio.json"


def load_portfolio():
    if not os.path.exists(PORTFOLIO_FILE):
        return {}

    with open(PORTFOLIO_FILE, "r") as f:
        return json.load(f)


def portfolio_exposure_to(instrument: str):
    portfolio = load_portfolio()
    position = portfolio.get(instrument)

    if not position:
        return 0.0

    return float(position.get("weight", 0.0))
``
