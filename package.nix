{
  lib,
  python3Packages,
}:
python3Packages.buildPythonApplication {
  pname = "gametrack-data";
  version = "0.1.0";
  pyproject = true;

  src = ./.;

  build-system = with python3Packages; [
    hatchling
  ];

  meta = {
    description = "Export GameTrack data to CSV";
    homepage = "https://github.com/josh/gametrack-data";
    license = lib.licenses.mit;
    platforms = lib.platforms.darwin;
    mainProgram = "gametrack-data";
  };
}
