{
  description = "Export GameTrack data to CSV";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
  };

  outputs =
    { self, nixpkgs }:
    let
      system = "aarch64-darwin";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      packages.${system} = {
        gametrack-data = pkgs.callPackage ./package.nix { };
        default = self.packages.${system}.gametrack-data;
      };
    };
}
