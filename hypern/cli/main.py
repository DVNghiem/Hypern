"""Main CLI entry point for Hypern."""

import argparse
import sys

from .scaffolding import NewCommand
from .run import RunCommand

# ANSI colours for HTTP methods
_METHOD_COLORS = {
    "GET": "\033[92m",      # green
    "POST": "\033[93m",     # yellow
    "PUT": "\033[94m",      # blue
    "DELETE": "\033[91m",   # red
    "PATCH": "\033[95m",    # magenta
    "HEAD": "\033[96m",     # cyan
    "OPTIONS": "\033[90m",  # grey
}
_RESET = "\033[0m"


def _print_routes_table(routes: list):
    """Pretty-print routes as a table."""
    if not routes:
        print("No routes registered.")
        return

    # Column widths
    mw = max(len(r.get("method", "")) for r in routes)
    pw = max(len(r.get("path", "")) for r in routes)
    mw = max(mw, 6)
    pw = max(pw, 4)

    header = f"{'METHOD':<{mw}}  {'PATH':<{pw}}  HANDLER"
    print(header)
    print("-" * len(header))
    for r in routes:
        method = r.get("method", "")
        path = r.get("path", "")
        handler = r.get("handler", "")
        color = _METHOD_COLORS.get(method, "")
        print(f"{color}{method:<{mw}}{_RESET}  {path:<{pw}}  {handler}")


def main():
    parser = argparse.ArgumentParser(
        prog="hypern",
        description="Hypern CLI - A Fast Async Python backend with a Rust runtime.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  hypern new myproject                    Create a new project with interactive pattern selection
  hypern new myproject --pattern layered  Create a new project with Layered architecture
  hypern run                              Run the Hypern application (auto-discovers app)
  hypern run --app myapp.app:app          Run a specific application instance
  hypern run --host 0.0.0.0 --port 8080  Run with custom host and port
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- hypern new ---
    new_parser = subparsers.add_parser(
        "new",
        help="Create a new Hypern project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Architecture patterns:
  layered          Layered / N-tier architecture
  ddd              Domain-Driven Design (DDD) + Layered
  hexagonal        Hexagonal (Ports & Adapters)
  onion            Onion Architecture
  clean            Clean Architecture
  cqrs             CQRS (Command-Query Responsibility Segregation)
  saga             SAGA pattern
  event-driven     Event-Driven / Event Sourcing
  saga-event       Combined SAGA + Event-Driven / Event Sourcing
        """,
    )
    new_parser.add_argument("name", help="Project name")
    new_parser.add_argument(
        "--pattern",
        "-p",
        choices=[
            "layered",
            "ddd",
            "hexagonal",
            "onion",
            "clean",
            "cqrs",
            "saga",
            "event-driven",
            "saga-event",
        ],
        default=None,
        help="Architecture pattern (interactive if omitted)",
    )
    new_parser.add_argument(
        "--directory",
        "-d",
        default=".",
        help="Parent directory for the new project (default: current directory)",
    )

    # --- hypern run ---
    run_parser = subparsers.add_parser("run", help="Run the Hypern application")
    run_parser.add_argument(
        "--app",
        "-a",
        default=None,
        help="Application instance path (e.g. myapp.app:app). Auto-discovers if omitted.",
    )
    run_parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    run_parser.add_argument("--port", type=int, default=5000, help="Port to bind (default: 5000)")
    run_parser.add_argument("--workers", "-w", type=int, default=1, help="Number of worker processes (default: 1)")
    run_parser.add_argument("--reload", action="store_true", help="Enable auto-reload on file changes")
    run_parser.add_argument("--debug", action="store_true", help="Enable debug mode")

    # --- hypern routes ---
    routes_parser = subparsers.add_parser("routes", help="List all registered routes")
    routes_parser.add_argument(
        "--app",
        "-a",
        default=None,
        help="Application instance path (e.g. myapp.app:app). Auto-discovers if omitted.",
    )
    routes_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output routes as JSON",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "new":
        cmd = NewCommand()
        cmd.execute(args)
    elif args.command == "run":
        cmd = RunCommand()
        cmd.execute(args)
    elif args.command == "routes":
        from .run import resolve_app
        app_instance = resolve_app(args.app)
        routes = app_instance.get_routes()
        if args.json_output:
            import json
            print(json.dumps(routes, indent=2))
        else:
            _print_routes_table(routes)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
