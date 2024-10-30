# GameTrack Data

Export [GameTrack](https://gametrack.app/) data to CSV.

## Installation

```sh
$ brew install josh/tap/gametrack-data
```

## Usage

```sh
$ gametrack-data --help
usage: gametrack-data [-h] [--output-filename FILENAME] [--metrics-filename FILENAME]
                      [--gh-repo GITHUB_REPOSITORY] [--gh-token GITHUB_TOKEN]

Export GameTrack data to CSV

options:
  -h, --help            show this help message and exit
  --output-filename FILENAME
                        Output CSV filename
  --metrics-filename FILENAME
                        Prometheus metrics filename
  --gh-repo GITHUB_REPOSITORY
                        GitHub repository
  --gh-token GITHUB_TOKEN
                        GitHub token
```
