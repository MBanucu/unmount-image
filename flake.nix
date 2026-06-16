{
  description = "unmount-image: Disk image unmount and detach via udisksctl (Linux)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    udisks-monitor.url = "github:MBanucu/udisks-monitor";
  };

  outputs =
    { self
    , nixpkgs
    , flake-utils
    , udisks-monitor
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [
            udisks-monitor.overlays.default
            self.overlays.default
          ];
        };
      in
      {
        packages.default = pkgs.python3.pkgs.unmount-image;

        devShells.default = pkgs.mkShell {
          inputsFrom = [ pkgs.python3.pkgs.unmount-image ];
          packages = [ pkgs.python3 ];
          shellHook = ''
            echo "unmount-image dev shell. Run tests:"
            echo "  python -m unittest discover -s tests -v"
          '';
        };
      }
    )
    // {
      overlays.default = final: prev: {
        unmount-image = final.python3.pkgs.callPackage ./default.nix {
          src = final.lib.cleanSource ./.;
          inherit (final.python3.pkgs) udisks-monitor;
        };
        python3 = prev.python3.override {
          packageOverrides = _: _: {
            inherit (final) unmount-image;
          };
        };
      };
    };
}
