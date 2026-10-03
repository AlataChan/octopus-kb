"""Replay publication keeps one winner and can regenerate a missing record."""

from __future__ import annotations

import json
import threading

from octopus_kb_compound.controls import InterpretationStore


def test_concurrent_publishers_return_the_same_winner(tmp_path):
    store = InterpretationStore(tmp_path)
    key = "ab" * 32
    results: list[str] = []
    errors: list[BaseException] = []

    def publish(text: str) -> None:
        try:
            results.append(store.publish(key, text))
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=publish, args=("alpha-body",)),
        threading.Thread(target=publish, args=("beta-body",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert errors == []
    assert results[0] == results[1]
    assert results[0] in {"alpha-body", "beta-body"}
    assert store.lookup(key) == results[0]
    index = json.loads((store.root / "index" / f"{key}.json").read_text(encoding="utf-8"))
    record = json.loads((store.root / "records" / f"{index['record_id']}.json").read_text(encoding="utf-8"))
    assert record["response_text"] == results[0]
    assert record["accepted"] is True


def test_evicted_winner_is_regenerated_and_then_replayable(tmp_path):
    store = InterpretationStore(tmp_path)
    key = "cd" * 32
    assert store.publish(key, "first-body") == "first-body"
    index = json.loads((store.root / "index" / f"{key}.json").read_text(encoding="utf-8"))
    record_id = index["record_id"]
    (store.root / "records" / f"{record_id}.json").unlink()

    missing = store.lookup(key)
    assert type(missing).__name__ == "ReplayUnavailable"
    assert missing.reason == "replay_unavailable"
    assert missing.record_id == record_id

    assert store.publish(key, "second-body") == "second-body"
    assert store.lookup(key) == "second-body"
    repaired = json.loads((store.root / "index" / f"{key}.json").read_text(encoding="utf-8"))
    record = json.loads((store.root / "records" / f"{repaired['record_id']}.json").read_text(encoding="utf-8"))
    assert repaired["record_id"] != record_id
    assert record["response_text"] == "second-body"
    assert record["regenerated_from"] == record_id
    assert store.publish(key, "third-body") == "second-body"
