{
  description = "Package flake using uv2nix";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = {
    self,
    nixpkgs,
    uv2nix,
    pyproject-nix,
    pyproject-build-systems,
    ...
  }: let
    inherit (nixpkgs) lib;

    workspace = uv2nix.lib.workspace.loadWorkspace {workspaceRoot = ./.;};

    overlay = workspace.mkPyprojectOverlay {
      sourcePreference = "wheel"; # or sourcePreference = "sdist";
    };

    pyprojectOverrides = _final: _prev: {
    };

    pkgs = nixpkgs.legacyPackages.x86_64-linux;

    python = pkgs.python312;

    pythonSet =
      (pkgs.callPackage pyproject-nix.build.packages {
        inherit python;
      }).overrideScope
      (
        lib.composeManyExtensions [
          pyproject-build-systems.overlays.default
          overlay
          pyprojectOverrides
        ]
      );

    # Use a similar procedure as https://medium.com/@daniel.garcia_57638/nix-nirvana-packaging-python-apps-with-uv2nix-c44e79ae4bc9 to use `nix run` to execute it.
    noogle_mcp_server-pkg = pythonSet."noogle-mcp-server";
    appPythonEnv = pythonSet.mkVirtualEnv (noogle_mcp_server-pkg.pname + "-env") workspace.deps.default;

    noogle_mcp_server = pkgs.stdenv.mkDerivation {
      pname = noogle_mcp_server-pkg.pname;
      version = noogle_mcp_server-pkg.version;
      src = ./.;
      nativeBuildInputs = [pkgs.makeWrapper];
      buildInputs = [appPythonEnv];
      installPhase = ''
        mkdir -p $out/bin
        cp ./noogle_mcp_server/__main__.py $out/bin/${noogle_mcp_server-pkg.pname}-script
        chmod +x $out/bin/${noogle_mcp_server-pkg.pname}-script
        makeWrapper ${appPythonEnv}/bin/python $out/bin/${noogle_mcp_server-pkg.pname} \
          --add-flags $out/bin/${noogle_mcp_server-pkg.pname}-script
      '';
    };
  in {
    packages.x86_64-linux.default = noogle_mcp_server;
    apps.x86_64-linux.default = {
      type = "app";
      program = "${self.packages.x86_64-linux.default}/bin/${noogle_mcp_server-pkg.pname}";
    };
    apps.x86_64-linux.${noogle_mcp_server-pkg.pname} = self.apps.x86_64-linux.default;
    devShells.x86_64-linux = rec {
      impure = pkgs.mkShell {
        packages = [
          python
          pkgs.uv
        ];
        env =
          {
            # Prevent uv from managing Python downloads
            UV_PYTHON_DOWNLOADS = "never";
            # Force uv to use nixpkgs Python interpreter
            UV_PYTHON = python.interpreter;
          }
          // lib.optionalAttrs pkgs.stdenv.isLinux {
            LD_LIBRARY_PATH = lib.makeLibraryPath pkgs.pythonManylinuxPackages.manylinux1;
          };
        shellHook = ''
          unset PYTHONPATH
        '';
      };

      uv2nix = let
        # Create an overlay enabling editable mode for all local dependencies.
        editableOverlay = workspace.mkEditablePyprojectOverlay {
          # Use environment variable
          root = "$REPO_ROOT";
        };

        # Override previous set with our overrideable overlay.
        editablePythonSet = pythonSet.overrideScope (
          lib.composeManyExtensions [
            editableOverlay

            # Apply fixups for building an editable package of your workspace packages
            (final: prev: {
              noogle_mcp_server = prev.noogle_mcp_server.overrideAttrs (old: {
                # It's a good idea to filter the sources going into an editable build
                # so the editable package doesn't have to be rebuilt on every change.
                src = lib.fileset.toSource {
                  root = old.src;
                  fileset = lib.fileset.unions [
                    (old.src + "/pyproject.toml")
                    (old.src + "/README.md")
                    (old.src + "/noogle_mcp_server/__init__.py")
                    (old.src + "/noogle_mcp_server/__main__.py")
                    (old.src + "/noogle_mcp_server/tools.py")
                  ];
                };
                nativeBuildInputs =
                  old.nativeBuildInputs
                  ++ final.resolveBuildSystem {
                    editables = [];
                  };
              });
            })
          ]
        );

        virtualenv = editablePythonSet.mkVirtualEnv "noogle-dev" workspace.deps.all;
      in
        pkgs.mkShell {
          packages = [
            virtualenv
            pkgs.uv
          ];

          env = {
            # Don't create venv using uv
            UV_NO_SYNC = "1";

            # Force uv to use Python interpreter from venv
            UV_PYTHON = "${virtualenv}/bin/python";

            # Prevent uv from downloading managed Python's
            UV_PYTHON_DOWNLOADS = "never";
          };

          shellHook = ''
            # Undo dependency propagation by nixpkgs.
            unset PYTHONPATH

            # Get repository root using git. This is expanded at runtime by the editable `.pth` machinery.
            export REPO_ROOT=$(git rev-parse --show-toplevel)
          '';
        };

      default = uv2nix;
    };
  };
}
