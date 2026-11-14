"""
Market Hub paper trading program (14 Nov 2026, owner: "start the paper trading program while we wait").

Runs on the Oracle machine market-hub-trader against the IBKR paper account, and on a laptop or GitHub against the
ICICI minute history (replay), with the same strategy and safety code in both:

  model.py     contracts, quotes, order requests, fills
  book.py      positions, cash, charges, profit and loss, marked to the latest prices
  risk.py      the safety limits every order passes through, and the kill switch
  engine.py    one step: mark the book, check the limits, ask the strategy, send what passes
  replay.py    prices and fills from the ICICI minute candles (private repo: state/breeze/expiry_weeks/, every
               session of an expiry from the owner's files, else state/breeze/expiry_days/, the two days around it)
  ibkr.py      prices and orders through the IBKR gateway on the machine (paper accounts only)
  journal.py   every decision, refusal, order and fill, one JSON line each
  strategies/  the rules; nothing trades unless a strategy is named in the run settings

Nothing here can reach a real-money account: ibkr.py refuses any account whose number does not start with "DU".
"""
