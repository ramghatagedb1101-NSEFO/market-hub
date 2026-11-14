"""Every decision, refusal, order, fill and the running profit, one JSON line each (append-only)."""
import json
from datetime import datetime
from pathlib import Path


class Journal:
    def __init__(self, path: str | None = None, echo: bool = False):
        self.path = Path(path) if path else None
        self.echo = echo
        self.lines: list[dict] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, now: datetime, kind: str, **data) -> None:
        row = {"t": now.isoformat(timespec="seconds"), "kind": kind, **data}
        self.lines.append(row)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, default=str) + "\n")
        if self.echo:
            print(json.dumps(row, default=str))

    def count(self, kind: str) -> int:
        return sum(1 for r in self.lines if r["kind"] == kind)
