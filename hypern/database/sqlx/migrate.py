# import os
# import sys
# import inspect
# import importlib
# import hashlib
# import argparse
# from datetime import datetime
# from typing import List, Type, Dict

# from hypern.config import get_config
# from .model import Model


# class MigrationManager:
#     """Manages database migrations and schema changes."""

#     def __init__(self, migrations_dir: str = "migrations"):
#         self.migrations_dir = migrations_dir
#         self.config = get_config()
#         self.ensure_migrations_dir()

#     def ensure_migrations_dir(self):
#         """Ensure migrations directory exists."""
#         if not os.path.exists(self.migrations_dir):
#             os.makedirs(self.migrations_dir)
#             # Create __init__.py to make it a package
#             with open(os.path.join(self.migrations_dir, "__init__.py"), "w") as f:
#                 pass

#     def collect_models(self) -> Dict[str, Type[Model]]:
#         """Collect all model classes from the project."""
#         models = {}
#         # Scan all Python files in the project directory
#         for root, _, files in os.walk("."):
#             if "venv" in root or "migrations" in root:
#                 continue
#             for file in files:
#                 if file.endswith(".py"):
#                     module_path = os.path.join(root, file)
#                     module_name = module_path.replace("/", ".").replace("\\", ".")[2:-3]
#                     try:
#                         module = importlib.import_module(module_name)
#                         for name, obj in inspect.getmembers(module):
#                             if inspect.isclass(obj) and issubclass(obj, Model) and obj != Model:
#                                 models[obj.__name__] = obj
#                     except (ImportError, AttributeError):
#                         continue
#         return models

#     def generate_migration(self, name: str):
#         """Generate a new migration file."""
#         timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#         migration_id = f"{timestamp}_{name}"
#         filename = f"{migration_id}.py"
#         filepath = os.path.join(self.migrations_dir, filename)

#         models = self.collect_models()

#         # Generate migration content
#         content = self._generate_migration_content(migration_id, models)

#         with open(filepath, "w") as f:
#             f.write(content)

#         print(f"Created migration: {filename}")

#     def _generate_migration_content(self, migration_id: str, models: Dict[str, Type[Model]]) -> str:
#         """Generate the content for a migration file."""
#         content = [
#             "from typing import List",
#             "from hypern.migrations import Migration\n",
#         ]

#         # Import all models
#         for model_name in models.keys():
#             content.append(f"from app.models import {model_name}")

#         content.extend([
#             "\n\nclass " + migration_id + "(Migration):",
#             "    \"\"\"",
#             "    Auto-generated migration.",
#             "    \"\"\"",
#             "",
#             "    def up(self) -> List[str]:",
#             "        return [",
#         ])

#         # Add CREATE TABLE statements
#         for model in models.values():
#             content.append(f"            '''{model.create_table_sql()}''',")

#         content.extend([
#             "        ]",
#             "",
#             "    def down(self) -> List[str]:",
#             "        return [",
#         ])

#         # Add DROP TABLE statements in reverse order
#         for model_name in reversed(list(models.keys())):
#             content.append(f"            '''DROP TABLE IF EXISTS {model_name.lower()} CASCADE;''',")

#         content.extend([
#             "        ]",
#             ""
#         ])

#         return "\n".join(content)

#     def get_applied_migrations(self) -> List[str]:
#         """Get list of applied migrations from database."""
#         session = get_session_database()
#         try:
#             result = session.execute("""
#                 SELECT migration_id FROM migrations
#                 ORDER BY applied_at;
#             """)
#             return [row[0] for row in result]
#         except Exception:
#             # Migrations table doesn't exist yet
#             return []

#     def apply_migrations(self, target: str = None):
#         """Apply pending migrations up to target (or all if target is None)."""
#         # Create migrations table if it doesn't exist
#         self._ensure_migrations_table()

#         # Get applied and available migrations
#         applied = set(self.get_applied_migrations())
#         available = self._get_available_migrations()

#         # Determine which migrations to apply
#         to_apply = []
#         for migration_id, module in available.items():
#             if migration_id not in applied:
#                 to_apply.append((migration_id, module))

#             if target and migration_id == target:
#                 break

#         # Apply migrations
#         session = get_session_database()
#         for migration_id, module in to_apply:
#             print(f"Applying migration: {migration_id}")

#             migration = module()
#             for sql in migration.up():
#                 session.execute(sql)

#             # Record migration
#             session.execute(
#                 "INSERT INTO migrations (migration_id, applied_at) VALUES (%s, NOW())",
#                 (migration_id,)
#             )
#             session.commit()

#     def rollback_migrations(self, target: str = None):
#         """Rollback migrations up to target (or last one if target is None)."""
#         applied = self.get_applied_migrations()
#         available = self._get_available_migrations()

#         # Determine which migrations to rollback
#         to_rollback = []
#         rollback_all = target == "zero"

#         for migration_id in reversed(applied):
#             to_rollback.append((migration_id, available[migration_id]))

#             if not rollback_all and (target == migration_id or target is None):
#                 break

#         # Rollback migrations
#         session = get_session_database()
#         for migration_id, module in to_rollback:
#             print(f"Rolling back migration: {migration_id}")

#             migration = module()
#             for sql in migration.down():
#                 session.execute(sql)

#             # Remove migration record
#             session.execute(
#                 "DELETE FROM migrations WHERE migration_id = %s",
#                 (migration_id,)
#             )
#             session.commit()

#     def _ensure_migrations_table(self):
#         """Ensure migrations table exists."""
#         session = get_session_database()
#         session.execute("""
#             CREATE TABLE IF NOT EXISTS migrations (
#                 migration_id VARCHAR(255) PRIMARY KEY,
#                 applied_at TIMESTAMP NOT NULL
#             );
#         """)
#         session.commit()

#     def _get_available_migrations(self) -> Dict[str, Type['Migration']]:
#         """Get available migrations from migrations directory."""
#         migrations = {}

#         for filename in sorted(os.listdir(self.migrations_dir)):
#             if filename.endswith(".py") and not filename.startswith("__"):
#                 migration_id = filename[:-3]
#                 module_name = f"{self.migrations_dir}.{migration_id}"
#                 module = importlib.import_module(module_name)

#                 for name, obj in inspect.getmembers(module):
#                     if (inspect.isclass(obj) and
#                         name == migration_id and
#                         hasattr(obj, 'up') and
#                         hasattr(obj, 'down')):
#                         migrations[migration_id] = obj

#         return migrations


# class Migration:
#     """Base class for database migrations."""

#     def up(self) -> List[str]:
#         """Return list of SQL statements to apply migration."""
#         raise NotImplementedError

#     def down(self) -> List[str]:
#         """Return list of SQL statements to rollback migration."""
#         raise NotImplementedError


# def main():
#     parser = argparse.ArgumentParser(description="Database migration tool")

#     subparsers = parser.add_subparsers(dest="command", help="Commands")

#     # makemigrations command
#     make_parser = subparsers.add_parser("makemigrations", help="Generate new migration")
#     make_parser.add_argument("name", help="Migration name")

#     # migrate command
#     migrate_parser = subparsers.add_parser("migrate", help="Apply migrations")
#     migrate_parser.add_argument("--target", help="Target migration (default: latest)")

#     # rollback command
#     rollback_parser = subparsers.add_parser("rollback", help="Rollback migrations")
#     rollback_parser.add_argument("--target", help="Target migration (default: last applied)")

#     args = parser.parse_args()

#     manager = MigrationManager()

#     if args.command == "makemigrations":
#         manager.generate_migration(args.name)
#     elif args.command == "migrate":
#         manager.apply_migrations(args.target)
#     elif args.command == "rollback":
#         manager.rollback_migrations(args.target)
#     else:
#         parser.print_help()


# if __name__ == "__main__":
#     main()
