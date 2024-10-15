import sqlite3
from pathlib import Path
import datetime
import csv
from typing import TypedDict, Iterator, Iterable, Literal
import argparse
import urllib.request
import urllib.parse
import json
import sys

GAMEDATA_PATH = (
    Path.home()
    / "Library"
    / "Containers"
    / "com.joekw.gametrack"
    / "Data"
    / "Library"
    / "Application Support"
    / "GameTrack"
    / "GameData.sqlite"
)

TBA_RELEASE_DATE = datetime.datetime(4000, 12, 31, 16, 0, 0)

CORE_DATA_EPOCH = datetime.datetime(2001, 1, 1)

GAME_STATUS = Literal[
    "In Progress",
    "Queued",
    "Collection",
    "Completed",
    "Abandoned",
    "Wanted",
]

GAME_STATUS_ENUM: dict[int, GAME_STATUS] = {
    1: "In Progress",
    2: "Queued",
    3: "Collection",
    4: "Completed",
    5: "Abandoned",
    6: "Wanted",
}

GAME_FIELDS = [
    "igdb_id",
    "wikidata_qid",
    "title",
    "status",
    "platform",
    "added_date",
    "release_date",
    "user_rating",
]


class Game(TypedDict):
    igdb_id: int
    wikidata_qid: str
    title: str
    status: GAME_STATUS
    platform: str
    added_date: str
    release_date: str
    user_rating: int


def _from_coredata_timestamp(timestamp: int | float) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(int(timestamp) + 978307200)


def _write_csv(filename: Path, games: Iterable[Game]) -> None:
    with open(filename, "w") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=GAME_FIELDS)
        writer.writeheader()
        writer.writerows(games)


_SPARQL_QUERY = """
SELECT ?item ?igdb_id WHERE {
  VALUES ?igdb_id { ?IGDB_IDS }
  ?item p:P5794 [ pq:P9043 ?igdb_id; rdf:type wikibase:BestRank ].
}
"""


def _load_wikidata_items(igdb_ids: Iterable[int]) -> dict[int, str]:
    igdb_ids_str = " ".join(f'"{igdb_id}"' for igdb_id in igdb_ids)
    assert len(igdb_ids_str) > 1
    query = _SPARQL_QUERY.replace("?IGDB_IDS", igdb_ids_str)
    data = urllib.parse.urlencode({"query": query}).encode("utf-8")

    req = urllib.request.Request(
        "https://query.wikidata.org/sparql",
        method="POST",
        data=data,
        headers={"Accept": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=60) as response:
        resp_data = json.load(response)

    results: dict[int, str] = {}
    for row in resp_data["results"]["bindings"]:
        qid = row["item"]["value"].split("/")[-1]
        assert qid.startswith("Q")
        igdb_id = int(row["igdb_id"]["value"])
        if igdb_id in results:
            print(
                f"WARN: Duplicate Wikidata items for IGDB ID {igdb_id}", file=sys.stderr
            )

        results[igdb_id] = qid

    return results


def _load_gametrack_games() -> Iterator[Game]:
    conn = sqlite3.connect(f"{GAMEDATA_PATH.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    wikidata_items = _load_wikidata_items(
        row["ZGAMEID"]
        for row in cursor.execute("SELECT ZGAMEID FROM ZGAME ORDER BY ZGAMEID ASC")
    )

    rows = cursor.execute("""
        SELECT ZGAMEID, ZTITLE, ZGAMESTATE, ZADDEDDATE, ZRELEASEDATE, ZUSERRATING, ZOWNEDPLATFORM
        FROM ZGAME
        ORDER BY ZGAMEID ASC
    """)

    for row in rows:
        assert isinstance(row["ZTITLE"], str)
        assert isinstance(row["ZGAMEID"], int)
        assert (
            row["ZADDEDDATE"] is None
            or isinstance(row["ZADDEDDATE"], int)
            or isinstance(row["ZADDEDDATE"], float)
        )
        assert row["ZRELEASEDATE"] is None or isinstance(row["ZRELEASEDATE"], int)
        assert row["ZUSERRATING"] is None or isinstance(row["ZUSERRATING"], int)
        assert row["ZOWNEDPLATFORM"] is None or isinstance(row["ZOWNEDPLATFORM"], str)

        igdb_id = row["ZGAMEID"]
        wikidata_qid = wikidata_items.get(igdb_id, "")
        title = row["ZTITLE"]
        status = GAME_STATUS_ENUM[row["ZGAMESTATE"]]
        platform = row["ZOWNEDPLATFORM"] or ""

        release_date = ""
        if row["ZRELEASEDATE"]:
            release_date = _from_coredata_timestamp(row["ZRELEASEDATE"]).strftime(
                "%Y-%m-%d"
            )
        else:
            release_date = ""

        if row["ZADDEDDATE"]:
            added_date = _from_coredata_timestamp(row["ZADDEDDATE"]).strftime(
                "%Y-%m-%d"
            )
        else:
            added_date = ""

        user_rating = row["ZUSERRATING"] if row["ZUSERRATING"] is not None else 0

        yield {
            "igdb_id": igdb_id,
            "wikidata_qid": wikidata_qid,
            "title": title,
            "status": status,
            "platform": platform,
            "added_date": added_date,
            "release_date": release_date,
            "user_rating": user_rating,
        }

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export GameTrack data to CSV")
    parser.add_argument(
        "--output-filename",
        metavar="FILENAME",
        type=str,
        required=True,
        help="Output CSV filename",
    )
    args = parser.parse_args()

    output_filename = Path(args.output_filename)
    games = _load_gametrack_games()

    _write_csv(filename=output_filename, games=games)


if __name__ == "__main__":
    main()
