"""Synthetic end-to-end runs against a fake Epic API; no network calls."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import analyze
import collect
import config
import store
from epic import EpicAPI

T0 = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=15)  # The new island appears at the top of the list.
OLD = dict(code="1111-1111-1111", creatorCode="veteran", title="Old Box Fights", createdIn="FNC",
           tags=["boxfight", "pvp"])
NEW = dict(code="2222-2222-2222", creatorCode="rookie", title="Steal the Brainrot Tycoon", createdIn="UEFN",
           tags=["tycoon", "simulator"])


def new_island_ccu(moment):
    age = moment - T1
    if age < timedelta(hours=2):
        return None
    if age < timedelta(hours=3):
        return 3
    return 80 if age < timedelta(hours=3, minutes=10) else 120


class FakeAPI(EpicAPI):
    def __init__(self, catalog):
        super().__init__(seconds=3600, rate=1e9)
        self.catalog = catalog
        self.series = {OLD["code"]: lambda moment: 500, NEW["code"]: new_island_ccu}
        self.paths = []

    def get(self, path, **params):
        self.paths.append(path)
        if path == "/islands":
            start, size = int(params.get("after") or 0), params["size"]
            following = start + size if start + size < len(self.catalog) else None
            return dict(data=self.catalog[start:start + size], meta=dict(page=dict(nextCursor=following and str(following))))
        if path == "/genres":
            return dict(data=[dict(slug="shooter", displayName="Shooter")])
        if path.startswith("/genres/"):
            return dict(meta=dict(total=2), data=[dict(islandCode=OLD["code"], rank=1), dict(islandCode=NEW["code"], rank=2)])
        parts = path.split("/")
        code = parts[2]
        if len(parts) == 3:
            return next((item for item in self.catalog if item["code"] == code), None)
        if parts[3] == "rankings":
            return dict(data=[dict(timestamp=params["from"], genres=[dict(genreSlug="shooter", genre="Shooter", rank=2)])])
        step = dict(minute=timedelta(minutes=10), hour=timedelta(hours=1), day=timedelta(days=1))[parts[4]]
        start, end = store.parse_time(params["from"]), store.parse_time(params["to"])
        moment = datetime.fromtimestamp(start.timestamp() // step.total_seconds() * step.total_seconds(), timezone.utc)
        points = []
        while moment < end:
            points.append((moment, self.series[code](moment)))
            moment += step
        metrics = params.get("metrics") or ["peakCCU", "plays", "uniquePlayers", "minutesPlayed", "favorites",
                                            "recommendations", "averageMinutesPerPlayer", "retention"]
        result = {}
        for metric in metrics:
            if metric == "retention":
                result[metric] = [dict(d1=0.3 if v else None, d7=0.1 if v else None, timestamp=store.utc_text(t)) for t, v in points]
            else:
                result[metric] = [dict(value=(v if metric == "peakCCU" else v * 2) if v else None,
                                       timestamp=store.utc_text(t)) for t, v in points]
        return result


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.data = Path(self.folder.name)
        self.state = {}

    def tearDown(self):
        self.folder.cleanup()

    def run_at(self, moment, catalog):
        api = FakeAPI(catalog)
        stats, notes = collect.run(api, self.state, moment, self.data, self.data / "catalog.json")
        self.assertEqual([], [n for n in notes if "error" in n])
        return api, stats

    def test_title_terms_merge_split_words(self):
        self.assertEqual({"steal", "brainrot", "steal brainrot"}, collect.title_terms("Steal the Brainrot!"))
        self.assertIn("brainrot", collect.title_terms("BRAIN ROT tycoon 2", frequent={"brainrot"}))
        self.assertNotIn("2", collect.title_terms("BRAIN ROT tycoon 2"))

    def test_pickup_needs_a_sudden_jump(self):
        base = T0
        stamp = lambda i: base + timedelta(minutes=10 * i)
        self.assertEqual((stamp(3), 5, 60), collect.detect_pickup([(stamp(0), None), (stamp(1), 3), (stamp(2), 5), (stamp(3), 60)]))
        self.assertIsNone(collect.detect_pickup([(stamp(i), v) for i, v in enumerate([10, 20, 40, 60, 90])]))

    def test_monthly_files_roll_over(self):
        original = config.FILE_BYTES
        config.FILE_BYTES = 10
        try:
            store.append_rows("things", ["a"], [dict(a="first row")], T0, self.data)
            store.append_rows("things", ["a"], [dict(a="second row")], T0, self.data)
        finally:
            config.FILE_BYTES = original
        self.assertEqual(["2026-09.csv", "2026-09-002.csv"], [p.name for p in store.partitions("things", self.data)])
        self.assertEqual(2, len(store.read_table("things", data_dir=self.data)))

    def test_launch_lifecycle(self):
        api, stats = self.run_at(T0, [OLD])
        self.assertEqual("seed", stats["catalog"])
        self.assertIn(OLD["code"], (self.data / "seed_codes.txt").read_text())
        self.assertEqual([], store.read_table("islands", data_dir=self.data))
        self.assertEqual([[OLD["code"], OLD["title"], OLD["creatorCode"]]], json.loads((self.data / "catalog.json").read_text(encoding="utf-8")))

        _, stats = self.run_at(T1, [NEW, OLD])
        islands = store.read_table("islands", data_dir=self.data)
        self.assertEqual([(NEW["code"], "head", store.utc_text(T1))], [(r["code"], r["source"], r["first_seen"]) for r in islands])
        self.assertTrue(store.read_table("rankings", data_dir=self.data))
        self.assertTrue(store.read_table("daily", data_dir=self.data), "ranked old island gets daily rows")

        self.run_at(T1 + timedelta(hours=3, minutes=30), [NEW, OLD])
        self.assertEqual(120, self.state["launch"][NEW["code"]]["peak"])
        self.run_at(T1 + timedelta(hours=25), [NEW, OLD])
        self.run_at(T1 + timedelta(hours=151), [NEW, OLD])
        self.run_at(T1 + timedelta(hours=152), [NEW, OLD])

        launches = {r["stage"]: r for r in store.read_table("launches", data_dir=self.data)}
        self.assertEqual({"24", "144"}, set(launches))
        pickup = store.utc_text(T1 + timedelta(hours=3, minutes=5))  # Epic buckets start on 10-minute marks.
        for row in launches.values():
            self.assertEqual(("120", pickup, "3.08"), (row["peak_ccu"], row["pickup_at"], row["hours_to_pickup"]))
        self.assertEqual(("2", "shooter", "0.3"), (launches["144"]["best_rank"], launches["144"]["best_rank_genre"], launches["144"]["d1"]))
        self.assertEqual(144, len(store.read_table("curves", data_dir=self.data)))
        pickups = store.read_table("pickups", data_dir=self.data)
        self.assertEqual([(NEW["code"], "launch", pickup)], [(r["code"], r["kind"], r["at"]) for r in pickups])
        daily = store.read_table("daily", data_dir=self.data)
        self.assertEqual(len(daily), len({(r["date"], r["code"]) for r in daily}), "daily rows are not duplicated")
        self.assertTrue(any(r["kind"] == "tag" and r["term"] == "tycoon" for r in store.read_table("keywords", data_dir=self.data)))

        result = analyze.analyze(self.data, self.state, T1 + timedelta(hours=152))
        cell = result["timing"]["all"][analyze.hour_of_week(store.utc_text(T1))]
        self.assertEqual([1, 1, 1, 1, 1, 1, 3.1, 120], cell)
        self.assertEqual({"all", "UEFN", "tag:tycoon", "tag:simulator"}, set(result["timing"]))
        self.assertEqual("Shooter", result["leaders"]["genres"][0]["name"])
        maps = analyze.map_records(self.data, self.state, T1 + timedelta(hours=152))["maps"]
        self.assertEqual(({"24", "144"}, 120, [[pickup, 3, 80]]), (set(maps[NEW["code"]]["launch"]), maps[NEW["code"]]["launch"]["144"]["peak_ccu"], maps[NEW["code"]]["surges"]))
        self.assertEqual(["shooter", 1], maps[OLD["code"]]["rank"][:2])

    def test_missing_search_index_triggers_catalog_crawl(self):
        self.run_at(T0, [OLD])
        (self.data / "catalog.json").unlink()
        _, stats = self.run_at(T0 + timedelta(minutes=15), [NEW, OLD])
        self.assertEqual("2 islands", stats["catalog"])
        self.assertEqual(2, len(json.loads((self.data / "catalog.json").read_text(encoding="utf-8"))))

    def test_unpublished_rankings_are_retried_not_stored(self):
        class Empty(FakeAPI):
            def get(self, path, **params):
                if path.startswith("/genres/"):
                    return dict(meta=dict(total=0), data=[])
                return super().get(path, **params)
        collect.run(Empty([OLD]), self.state, T0, self.data)
        self.assertEqual([], store.read_table("rankings", data_dir=self.data))
        self.assertTrue(all(h < store.utc_text(T0 - timedelta(hours=config.RANKING_GIVE_UP_HOURS)) for h in self.state["dead_rank_hours"]))


if __name__ == "__main__":
    unittest.main()
