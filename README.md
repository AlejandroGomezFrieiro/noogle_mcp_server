# Noogle Server

This project provides a tool for querying Nix built-in and Nixpkgs function documentation from [noogle.dev](https://noogle.dev). It leverages `uv2nix` for robust packaging and reproducible development environments.

## Why write this?

The major reason to write it was to test for myself how much can I push an AI-assisted workflow using [codecompanion](https://codecompanion.olimorris.dev/) inside [my custom neovim configuration](https://github.com/AlejandroGomezFrieiro/nixvim_config). I am not a web developer and, as part of my day-to-day job I also do not have to write any REST API. So I wanted to challenge myself to test `uv2nix` (which I always found and still kind of find difficult to use) and figure out what kind of things work and what does not work when doing AI-assisted development.  

## Features

*   **Nix Documentation Query**: Uses the `query_nix_docs` tool to fetch and parse documentation from `noogle.dev`.
*   **Structured Output**: Presents documentation in a clear Markdown format, including inputs, types, examples, and aliases.
*   **Pure Nix Development**: Provides a pure development shell using `uv2nix` for consistent, reproducible environments with editable installs.
*   **Impure Development**: Supports an impure development workflow for those who prefer managing their Python virtual environments with `uv` directly.

## Usage

### Nix

The output of `flake.nix` contains a script to start the server. After cloning the repository, you can do

```bash
nix run .

```
### Standard Python

The `nix-docs-server` is an application that exposes the `query_nix_docs` functionality as a service (via FastMCP). After cloning the repository, you can run the server using one of the following:

```bash
python -m noogle_mcp_server.main
```

## Development

This project offers two modes for setting up development environments using Nix: a pure Nix-managed environment leveraging `uv2nix` and an impure environment that uses `uv` directly.

### Prerequisites

*   [Nix](https://nixos.org/download)
    * Must also have `flakes` experimental feature setup.

### Impure Development (`nix develop .#impure`)

This development shell sets up `python312` and `uv` from Nixpkgs. It configures `uv` to use the Nix-provided Python interpreter and prevents it from downloading its own, while allowing you to manage your Python virtual environment (e.g., using `uv venv`) outside of Nix. This is suitable if you prefer a traditional `uv`-based workflow.

```bash
nix develop .#impure
# Inside the shell, you can use uv:
# uv venv
# source .venv/bin/activate
```

### Pure Development (`nix develop .#uv2nix` or `nix develop`)

This shell provides a purely Nix-built virtual environment with your project's dependencies. It uses `uv2nix` to create an isolated, reproducible environment and enables "editable" installs for your local project files. This means changes to your source code are reflected immediately in the virtual environment without requiring a Nix rebuild.

```bash
nix develop .#uv2nix
# Or simply use the default shell:
nix develop
```

Once inside this shell, your local project files (e.g., `noogle_mcp_server/`) are installed in "editable" mode, allowing for immediate reflection of code changes.

This environment provides the benefits of Nix's reproducibility while maintaining a flexible development experience for Python projects.
