{
  description = "A Discord bot that watches RSS feeds";

  outputs = { nixpkgs, ... }:
    let
      forAllSystems = gen:
        nixpkgs.lib.genAttrs nixpkgs.lib.systems.flakeExposed
        (system: gen nixpkgs.legacyPackages.${system});
    in {
      packages = forAllSystems (pkgs: { default = pkgs.callPackage ./. { }; });
    };
}
