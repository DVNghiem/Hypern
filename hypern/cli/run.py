"""hypern run - Run the Hypern application."""

import importlib
import os
import sys


class RunCommand:
    """Handles the `hypern run` CLI command."""

    # Common module:attribute patterns to auto-discover
    _DISCOVERY_PATTERNS = [
        ("app", "app"),
        ("app", "application"),
        ("main", "app"),
        ("main", "application"),
        ("server", "app"),
        ("server", "application"),
        ("application", "app"),
        ("application", "application"),
    ]

    def execute(self, args):
        app_path = args.app
        host = args.host
        port = args.port
        workers = args.workers
        reload_enabled = args.reload
        debug = args.debug

        # Ensure cwd is on sys.path so imports work
        cwd = os.getcwd()
        if cwd not in sys.path:
            sys.path.insert(0, cwd)

        if app_path:
            app = self._import_app(app_path)
        else:
            app = self._discover_app()

        if app is None:
            print(
                "\033[91mError:\033[0m Could not find a Hypern application instance.\n"
                "Specify one with --app module:attribute (e.g. --app app:app)"
            )
            sys.exit(1)

        # Apply CLI overrides
        if debug:
            app.debug = True

        print(
            f"\033[96m⚡ Hypern\033[0m starting on "
            f"\033[1m{host}:{port}\033[0m "
            f"(workers={workers}, reload={reload_enabled})"
        )
        app.start(host=host, port=port, num_processes=workers)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _import_app(self, app_path: str):
        """Import app from 'module:attribute' string."""
        if ":" not in app_path:
            print(f"Error: Invalid app path '{app_path}'. Expected format: module:attribute")
            sys.exit(1)

        module_path, attr_name = app_path.rsplit(":", 1)
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            print(f"Error: Could not import module '{module_path}': {exc}")
            sys.exit(1)

        app = getattr(module, attr_name, None)
        if app is None:
            print(f"Error: Module '{module_path}' has no attribute '{attr_name}'")
            sys.exit(1)

        return app

    def _discover_app(self):
        """Try to auto-discover a Hypern app instance."""
        from hypern.application import Hypern

        for module_name, attr_name in self._DISCOVERY_PATTERNS:
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue

            obj = getattr(module, attr_name, None)
            if obj is not None and isinstance(obj, Hypern):
                print(f"Auto-discovered app: {module_name}:{attr_name}")
                return obj

        # Fallback: scan top-level py files in cwd for Hypern instances
        cwd = os.getcwd()
        for fname in sorted(os.listdir(cwd)):
            if not fname.endswith(".py"):
                continue
            mod_name = fname[:-3]
            if mod_name.startswith("_"):
                continue
            try:
                module = importlib.import_module(mod_name)
            except Exception:
                continue
            for attr_name in dir(module):
                obj = getattr(module, attr_name, None)
                if isinstance(obj, Hypern):
                    print(f"Auto-discovered app: {mod_name}:{attr_name}")
                    return obj

        return None
