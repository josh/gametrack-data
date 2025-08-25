import argparse
import csv
import datetime
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from io import StringIO
from pathlib import Path
from typing import Any, Literal, TextIO, TypedDict, Union, cast

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

WIKIDATA_USER_AGENT = "gametrack-data (https://github.com/josh/gametrack-data)"

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

RATINGS_ENUM = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

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
    release_year: int
    release_date: str
    user_rating: int


def _from_coredata_timestamp(timestamp: Union[int, float]) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(int(timestamp) + 978307200)


def _read_csv(filename: str) -> Iterator[Game]:
    with open(filename) as f:
        for row in csv.DictReader(f):
            if row["igdb_id"]:
                row["igdb_id"] = int(row["igdb_id"])
            if "release_year" not in row:
                if row["release_date"]:
                    row["release_year"] = int(row["release_date"].split("-")[0])
                else:
                    row["release_year"] = 0
            if row["user_rating"]:
                row["user_rating"] = int(row["user_rating"])
            yield cast(Game, row)


def _write_csv(f: TextIO, games: Iterable[Game]) -> int:
    writer = csv.DictWriter(f, fieldnames=GAME_FIELDS)
    writer.writeheader()
    count = 0
    for game in games:
        row = {field: game.get(field) for field in GAME_FIELDS}
        writer.writerow(row)
        count += 1
    return count


def _write_prom_metrics(f: TextIO, games: list[Game]) -> int:
    count = 0
    counts: dict[tuple[int, str, GAME_STATUS], int] = {}
    ratings: dict[tuple[int, int], int] = {}

    platforms = sorted(game["platform"] for game in games)
    years = sorted(game["release_year"] for game in games)

    for status in GAME_STATUS_ENUM.values():
        for year in years:
            for platform in platforms:
                counts[(year, platform, status)] = 0
                for rating in RATINGS_ENUM:
                    ratings[(rating, year)] = 0

    for game in games:
        year = game["release_year"]
        platform = game["platform"]
        status = game["status"]
        counts[(year, platform, status)] += 1
        if user_rating := game["user_rating"]:
            ratings[(user_rating, year)] += 1

    f.write("# HELP gametrack_game_count Number of games\n")
    f.write("# TYPE gametrack_game_count gauge\n")
    for (year, platform, status), value in counts.items():
        f.write(
            f'gametrack_game_count{{year="{year}",platform="{platform}",status="{status}"}} {value:.1f}\n'
        )
        count += 1

    f.write("# HELP gametrack_game_rating Game rating\n")
    f.write("# TYPE gametrack_game_rating gauge\n")
    for (rating, year), value in ratings.items():
        f.write(
            f'gametrack_game_rating{{year="{year}",rating="{rating}"}} {value:.1f}\n'
        )
        count += 1

    return count


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
    post_data = urllib.parse.urlencode({"query": query}).encode("utf-8")

    req = urllib.request.Request(
        "https://query.wikidata.org/sparql",
        method="POST",
        data=post_data,
        headers={
            "Accept": "application/json",
            "User-Agent": WIKIDATA_USER_AGENT,
        },
    )

    with urllib.request.urlopen(req, timeout=60) as response:
        data = json.load(response)

    results: dict[int, str] = {}
    for row in data["results"]["bindings"]:
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
            d = _from_coredata_timestamp(row["ZRELEASEDATE"])
            release_date = d.strftime("%Y-%m-%d")
            release_year = d.year
        else:
            release_date = ""
            release_year = 0

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
            "release_year": release_year,
            "release_date": release_date,
            "user_rating": user_rating,
        }

    conn.close()


def _gh_api_get(path: str, github_token: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        method="GET",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.load(response)
        assert isinstance(data, dict)
        return data


def _gh_api_post(path: str, body: dict[str, Any], github_token: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.load(response)
        assert isinstance(data, dict)
        return data


def _gh_create_blob(repo: str, github_token: str, content: str) -> str:
    data = _gh_api_post(
        path=f"/repos/{repo}/git/blobs",
        body={"content": content, "encoding": "utf-8"},
        github_token=github_token,
    )
    sha = data["sha"]
    assert isinstance(sha, str)
    assert len(sha) == 40
    return sha


class _GitTreeEntry(TypedDict):
    path: str
    mode: str
    type: Literal["blob", "tree"]
    sha: str


def _gh_create_tree(repo: str, github_token: str, tree: Iterable[_GitTreeEntry]) -> str:
    data = _gh_api_post(
        path=f"/repos/{repo}/git/trees",
        body={"tree": list(tree)},
        github_token=github_token,
    )
    sha = data["sha"]
    assert isinstance(sha, str)
    assert len(sha) == 40
    return sha


def _gh_create_commit(
    repo: str, message: str, tree_sha: str, parent_sha: str, github_token: str
) -> str:
    data = _gh_api_post(
        path=f"/repos/{repo}/git/commits",
        body={
            "message": message,
            "parents": [parent_sha],
            "tree": tree_sha,
        },
        github_token=github_token,
    )
    sha = data["sha"]
    assert isinstance(sha, str)
    assert len(sha) == 40
    return sha


def _gh_branch_sha(repo: str, name: str, github_token: str) -> tuple[str, str]:
    data = _gh_api_get(
        path=f"/repos/{repo}/git/ref/heads/{name}",
        github_token=github_token,
    )
    assert data["object"]["type"] == "commit"
    commit_sha = data["object"]["sha"]
    assert isinstance(commit_sha, str)
    assert len(commit_sha) == 40

    data = _gh_api_get(
        path=f"/repos/{repo}/git/commits/{commit_sha}",
        github_token=github_token,
    )
    tree_sha = data["tree"]["sha"]
    assert isinstance(tree_sha, str)
    assert len(tree_sha) == 40

    return commit_sha, tree_sha


def _gh_update_branch(repo: str, name: str, commit_sha: str, github_token: str) -> None:
    data = _gh_api_post(
        path=f"/repos/{repo}/git/refs/heads/{name}",
        body={"sha": commit_sha, "force": False},
        github_token=github_token,
    )
    assert data["object"]["type"] == "commit"
    assert data["object"]["sha"] == commit_sha
    print(f"Updated '{repo}/{name}' to {commit_sha}", file=sys.stderr)


def _gh_commit_tree(
    repo: str,
    github_token: str,
    branch: str,
    message: str,
    tree: Iterable[_GitTreeEntry],
) -> str:
    previous_commit_sha, previous_tree_sha = _gh_branch_sha(repo, branch, github_token)
    new_tree_sha = _gh_create_tree(repo, github_token, tree)

    if previous_tree_sha == new_tree_sha:
        print(f"'{repo}/{branch}' already {new_tree_sha}", file=sys.stderr)
        return previous_commit_sha

    new_commit_sha = _gh_create_commit(
        repo=repo,
        message=message,
        tree_sha=new_tree_sha,
        parent_sha=previous_commit_sha,
        github_token=github_token,
    )
    _gh_update_branch(
        repo,
        branch,
        new_commit_sha,
        github_token,
    )
    return new_commit_sha


def _upload_github(repo: str, github_token: str, games: list[Game]) -> None:
    gamedata = StringIO()
    rows = _write_csv(gamedata, games)
    print(f"Uploading {rows} games", file=sys.stderr)

    tree: list[_GitTreeEntry] = [
        {
            "path": "games.csv",
            "mode": "100644",
            "type": "blob",
            "sha": _gh_create_blob(repo, github_token, gamedata.getvalue()),
        },
    ]

    _gh_commit_tree(
        repo=repo,
        github_token=github_token,
        branch="data",
        message="Update data",
        tree=tree,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="GameTrack data exporter")
    subparsers = parser.add_subparsers(
        dest="command",
        metavar="COMMAND",
        help="Subcommand to run",
    )

    export_parser = subparsers.add_parser(
        "export",
        help="Export GameTrack database to CSV",
    )
    export_parser.add_argument(
        "--output-filename",
        metavar="FILENAME",
        type=str,
        help="Output CSV filename",
    )
    export_parser.add_argument(
        "--metrics-filename",
        metavar="FILENAME",
        type=str,
        help="Prometheus metrics filename",
    )
    export_parser.add_argument(
        "--gh-repo", metavar="GITHUB_REPOSITORY", type=str, help="GitHub repository"
    )
    export_parser.add_argument(
        "--gh-token",
        metavar="GITHUB_TOKEN",
        type=str,
        help="GitHub token",
    )

    metrics_parser = subparsers.add_parser(
        "metrics",
        help="Generate metrics from CSV data",
    )
    metrics_parser.add_argument(
        "--input-filename",
        metavar="FILENAME",
        type=str,
        help="Input CSV filename",
    )
    metrics_parser.add_argument(
        "--metrics-filename",
        metavar="FILENAME",
        type=str,
        default="-",
        help="Prometheus metrics filename",
    )

    args = parser.parse_args()
    command = args.command or "export"

    if command == "metrics":
        exitcode = 1
        games = list(_read_csv(filename=args.input_filename))

        if args.metrics_filename == "-":
            _write_prom_metrics(sys.stdout, games)
        else:
            with open(args.metrics_filename, "w") as f:
                _write_prom_metrics(f, games)
        exitcode = 0

        exit(exitcode)

    elif command == "export":
        github_repo: str | None = getattr(args, "gh_repo", None) or os.environ.get(
            "GITHUB_REPOSITORY"
        )
        github_token: str | None = getattr(args, "gh_token", None) or os.environ.get(
            "GITHUB_TOKEN"
        )

        exitcode = 1
        games = list(_load_gametrack_games())

        if filename := getattr(args, "output_filename", None):
            with open(filename, "w") as csvfile:
                count = _write_csv(csvfile, games)
                print(f"Wrote {count} rows to {filename}", file=sys.stderr)
            exitcode = 0

        if filename := getattr(args, "metrics_filename", None):
            with open(filename, "w") as f:
                _write_prom_metrics(f, games)
            exitcode = 0

        if github_repo and github_token:
            _upload_github(
                repo=github_repo,
                github_token=github_token,
                games=games,
            )
            exitcode = 0

        exit(exitcode)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
