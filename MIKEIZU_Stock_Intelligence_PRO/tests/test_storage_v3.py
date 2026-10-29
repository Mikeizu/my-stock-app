import sqlite3

import pytest

import storage


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "data" / "watchlist.sqlite3"
    monkeypatch.setattr(storage, "DB", path)
    return path


def test_composite_country_symbol_identity(database):
    storage.save("ABC", "US issuer", 10, country="United States")
    storage.save("ABC", "UK issuer", 20, country="United Kingdom")
    rows = storage.all_items()
    assert len(rows) == 2
    assert set(rows["country"]) == {"United States", "United Kingdom"}
    storage.remove("ABC", country="United States")
    rows = storage.all_items()
    assert len(rows) == 1
    assert rows.iloc[0]["thesis"] == "UK issuer"


def test_migrates_legacy_watchlist_without_losing_notes_prices_or_added_dates(database):
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE watchlist(symbol TEXT PRIMARY KEY,added_at TEXT NOT NULL,thesis TEXT NOT NULL,target_price REAL)")
        db.executemany("INSERT INTO watchlist VALUES(?,?,?,?)", [
            ("KO", "2025-01-01", "Keep original thesis", 50),
            ("VOD.L", "2025-01-02", "UK position", 100),
            ("GTCO.NGX", "2025-01-03", "NG position", None),
        ])
    rows = storage.all_items().set_index("symbol")
    assert rows.loc["KO", "thesis"] == "Keep original thesis"
    assert rows.loc["KO", "added_at"] == "2025-01-01"
    assert rows.loc["KO", "target_price"] == 50
    assert rows.loc["VOD.L", "country"] == "United Kingdom"
    assert rows.loc["GTCO.NGX", "country"] == "Nigeria"
    # Reopening the already migrated database must preserve exactly these rows.
    assert len(storage.all_items()) == 3
    storage.save("KO", "Updated", 60)
    assert len(storage.all_items()) == 3
    assert storage.all_items().set_index("symbol").loc["KO", "added_at"] == "2025-01-01"


@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf")])
def test_invalid_review_price_does_not_write(database, price):
    with pytest.raises(ValueError, match="Review price"):
        storage.save("KO", target_price=price)
    assert not database.exists()


def test_invalid_country_does_not_write(database):
    with pytest.raises(ValueError, match="listing country"):
        storage.save("KO", country="Not a supported market")
    assert not database.exists()


def test_migration_failure_rolls_back_original_table(database):
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE watchlist(symbol TEXT PRIMARY KEY,added_at TEXT NOT NULL,thesis TEXT NOT NULL,target_price REAL)")
        db.execute("INSERT INTO watchlist VALUES('KO','2025-01-01','Original',50)")
        # An unexpected staging table must not cause loss of original user rows.
        db.execute("CREATE TABLE watchlist_v3(blocked TEXT)")
    with pytest.raises(sqlite3.OperationalError):
        storage.all_items()
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT thesis FROM watchlist").fetchone()[0] == "Original"
        assert "country" not in {x[1] for x in db.execute("PRAGMA table_info(watchlist)")}
