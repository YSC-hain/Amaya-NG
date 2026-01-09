{
  description = "Python dev env (NixOS)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        py = pkgs.python312;
      in {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            py
            uv
            ruff
            pyright
            git

            # 常见“带原生扩展”的 Python 包会用到的依赖（按需增删）
            pkg-config
            openssl
            zlib
            libffi
            sqlite
          ];

          env = {
            UV_PYTHON = "${py}/bin/python";
            PIP_DISABLE_PIP_VERSION_CHECK = "1";
          };

          shellHook = ''
            export VIRTUAL_ENV="$PWD/.venv"
            export PATH="$VIRTUAL_ENV/bin:$PATH"

            if [ ! -d "$VIRTUAL_ENV" ]; then
              uv venv "$VIRTUAL_ENV"
            fi
          '';
        };
      });
}
