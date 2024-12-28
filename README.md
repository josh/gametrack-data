# GameTrack Data

Export [GameTrack](https://gametrack.app/) data to CSV.

## Installation

Via [Homebrew](https://brew.sh/):

```sh
$ brew install josh/tap/gametrack-data
```

Or via [Nix](https://nixos.org/):

```sh
$ nix run github:josh/nurpkgs#gametrack-data -- --help
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
