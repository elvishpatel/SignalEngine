from __future__ import annotations

import argparse
from typing import Any

from signal_engine.utils import load_rules


class RuleEvaluator:
    def __init__(self, rules_config: dict[str, Any] | None = None):
        self.rules_config = rules_config or load_rules()
        self.rules = self.rules_config.get("rules", [])

    def evaluate(self, signal_dict: dict[str, Any], active_event_types: list[str]) -> float:
        active = set(active_event_types)
        adjusted = float(signal_dict.get("confidence", 0.0))
        for rule in self.rules:
            conditions = rule.get("conditions", {})
            if all((flag is True and event_type in active) for event_type, flag in conditions.items()):
                adjusted += float(rule.get("score_boost", 0.0))
        return adjusted


def main() -> None:
    evaluator = RuleEvaluator()
    print(evaluator.evaluate({"confidence": 1.0}, ["BULK_DEAL", "SECTOR_ROTATION"]))


if __name__ == "__main__":
    main()
