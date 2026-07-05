import json
from datetime import datetime, timezone


class ReconciliationReport:
    def __init__(self) -> None:
        self.entities: dict[str, dict[str, int]] = {}
        self.errors: list[dict[str, str]] = []
        self.started_at = datetime.now(timezone.utc).isoformat()

    def record_entity(self, name: str, source_count: int, loaded_count: int) -> None:
        self.entities[name] = {
            "source_count": source_count,
            "loaded_count": loaded_count,
            "discrepancy": source_count - loaded_count,
        }

    def record_error(self, entity: str, vp_source_key: str, message: str) -> None:
        self.errors.append(
            {"entity": entity, "vp_source_key": vp_source_key, "message": message}
        )

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "entities": self.entities,
            "errors": self.errors,
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def print_summary(self) -> None:
        print("\n=== Reconciliation Report ===")
        for name, counts in self.entities.items():
            flag = "  <-- MISMATCH" if counts["discrepancy"] != 0 else ""
            print(
                f"  {name:30s} source={counts['source_count']:>7} "
                f"loaded={counts['loaded_count']:>7}{flag}"
            )
        print(f"  errors logged: {len(self.errors)}")
