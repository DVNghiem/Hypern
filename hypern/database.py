from __future__ import annotations
from typing import Protocol, runtime_checkable
from collections import OrderedDict

from typing import Any, Dict, List, Optional, Union
from contextlib import contextmanager

from hypern._hypern import (
    ConnectionPool as _ConnectionPool,
    PoolConfig as _PoolConfig,
    PoolStatus as _PoolStatus,
    DbSession as _DbSession,
    AnyPool as _AnyPool,
    get_db as _get_db,
    finalize_db as _finalize_db,
    finalize_db_all as _finalize_db_all,
)


class Database:
    """
    Database manager for the Hypern framework.
    
    Provides a convenient API for configuring and accessing multiple database connection pools.
    Configuration is stored and initialization is deferred until first use (lazy initialization).
    This allows the database to work correctly with fork-based multiprocessing.
    
    Supported DSN schemes:
    
    - ``postgresql://`` / ``postgres://`` — Uses the high-performance deadpool-postgres backend
    - ``mysql://`` — Uses the sqlx Any driver
    - ``sqlite://`` — Uses the sqlx Any driver
    """
    
    _databases: Dict[str, Dict[str, Any]] = {}
    _initialized_pools: Dict[str, bool] = {}
    _any_pools: Dict[str, "_AnyPool"] = {}
    
    @classmethod
    def configure(
        cls,
        url: str,
        max_size: int = 16,
        min_idle: Optional[int] = None,
        connect_timeout_secs: int = 30,
        idle_timeout_secs: Optional[int] = None,
        max_lifetime_secs: Optional[int] = None,
        test_before_acquire: bool = False,
        keepalive_secs: Optional[int] = None,
        alias: str = "default",
    ) -> None:
        """
        Configure a database connection pool with an alias (lazy initialization).
        
        The actual pool is initialized lazily on first use. This allows the configuration
        to be set before fork() in multiprocess servers, with each worker process
        initializing its own connection pools.
        
        Args:
            url: Database connection URL. Supported schemes:
                - ``postgresql://user:pass@host:port/database`` (or ``postgres://``)
                - ``mysql://user:pass@host:port/database``
                - ``sqlite:///path/to/db.sqlite`` (or ``sqlite::memory:``)
            max_size: Maximum number of connections in the pool (default: 16)
            min_idle: Minimum idle connections to maintain (default: None, PostgreSQL only)
            connect_timeout_secs: Connection timeout in seconds (default: 30, PostgreSQL only)
            idle_timeout_secs: Idle connection timeout in seconds (default: None, PostgreSQL only)
            max_lifetime_secs: Maximum connection lifetime in seconds (default: None, PostgreSQL only)
            test_before_acquire: If True, test connections before acquiring them (default: False, PostgreSQL only)
            keepalive_secs: TCP keepalive interval in seconds (default: None, PostgreSQL only)
            alias: Database alias for identification (default: "default")
        
        Raises:
            RuntimeError: If database with this alias is already configured
        """
        if alias in cls._databases:
            raise RuntimeError(f"Database with alias '{alias}' already configured. Call Database.close('{alias}') first to reconfigure.")
        
        driver = _detect_driver(url)
        
        cls._databases[alias] = {
            'url': url,
            'max_size': max_size,
            'min_idle': min_idle,
            'connect_timeout_secs': connect_timeout_secs,
            'idle_timeout_secs': idle_timeout_secs,
            'max_lifetime_secs': max_lifetime_secs,
            'test_before_acquire': test_before_acquire,
            'keepalive_secs': keepalive_secs,
            'alias': alias,
            'driver': driver,
        }
        cls._initialized_pools[alias] = False
    
    @classmethod
    def _ensure_initialized(cls, alias: str = "default") -> None:
        """Ensure the pool for the specified alias is initialized (lazy initialization)."""
        if cls._initialized_pools.get(alias, False):
            return
        if alias not in cls._databases:
            raise RuntimeError(f"Database '{alias}' not configured. Call Database.configure() first.")
        
        config_data = cls._databases[alias]
        driver = config_data.get('driver', 'postgres')
        
        if driver == 'postgres':
            config = _PoolConfig(
                url=config_data['url'],
                max_size=config_data['max_size'],
                min_idle=config_data['min_idle'],
                connect_timeout_secs=config_data['connect_timeout_secs'],
                idle_timeout_secs=config_data['idle_timeout_secs'],
                max_lifetime_secs=config_data['max_lifetime_secs'],
                test_before_acquire=config_data['test_before_acquire'],
                keepalive_secs=config_data['keepalive_secs'],
            )
            _ConnectionPool.initialize_with_alias(config, alias)
        else:
            # MySQL / SQLite via sqlx AnyPool
            pool = _AnyPool(config_data['url'], config_data['max_size'])
            cls._any_pools[alias] = pool
        
        cls._initialized_pools[alias] = True
    
    @classmethod
    def is_configured(cls, alias: str = "default") -> bool:
        """Check if the database with the specified alias is configured."""
        return alias in cls._databases
    
    @classmethod
    def status(cls, alias: str = "default") -> Optional[_PoolStatus]:
        """
        Get the current pool status for the specified alias.
        
        Args:
            alias: Database alias (default: "default")
            
        Returns:
            PoolStatus with size, available, and max_size properties, or None if not configured.
        """
        return _ConnectionPool.status_for_alias(alias)
    
    @classmethod
    def close(cls, alias: Optional[str] = None) -> None:
        """
        Close connections and reset the pool(s).
        
        Args:
            alias: Database alias to close. If None, closes all databases.
        """
        if alias is None:
            _ConnectionPool.close_all()
            for p in cls._any_pools.values():
                p.close()
            cls._any_pools.clear()
            cls._databases.clear()
            cls._initialized_pools.clear()
        else:
            if alias in cls._any_pools:
                cls._any_pools.pop(alias).close()
            if alias in cls._databases:
                driver = cls._databases[alias].get('driver', 'postgres')
                if driver == 'postgres':
                    _ConnectionPool.close_alias(alias)
                del cls._databases[alias]
                cls._initialized_pools.pop(alias, None)


class DbSession:
    """
    Request-scoped database session.
    
    Provides methods for executing SQL queries within a request context.
    Each request gets exactly one database connection from the pool.
    
    Attributes:
        request_id: The unique identifier of the associated request
    """
    
    def __init__(self, session: _DbSession):
        self._session = session
    
    @property
    def request_id(self) -> str:
        """Get the request ID associated with this session."""
        return self._session.request_id
    
    def begin(self) -> "DbSession":
        """
        Begin a database transaction.
        
        Returns:
            self for method chaining
        
        Raises:
            RuntimeError: If a transaction is already active
        """
        self._session.begin()
        return self
    
    def commit(self) -> "DbSession":
        """
        Commit the current transaction.
        
        Returns:
            self for method chaining
        
        Raises:
            RuntimeError: If no transaction is active
        """
        self._session.commit()
        return self
    
    def rollback(self) -> "DbSession":
        """
        Rollback the current transaction.
        
        Returns:
            self for method chaining
        
        Raises:
            RuntimeError: If no transaction is active
        """
        self._session.rollback()
        return self
    
    def query(
        self,
        sql: str,
        params: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a SELECT query and return results as a list of dictionaries.
        
        Args:
            sql: SQL query with $1, $2, etc. placeholders
            params: List of parameter values
        
        Returns:
            List of dictionaries, one per row
        
        Example:
            users = session.query(
                "SELECT * FROM users WHERE status = $1",
                ["active"]
            )
        """
        return self._session.query(sql, params)
    
    def query_one(
        self,
        sql: str,
        params: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a SELECT query and return a single result.
        
        Args:
            sql: SQL query with $1, $2, etc. placeholders
            params: List of parameter values
        
        Returns:
            Dictionary representing the row
        
        Raises:
            RuntimeError: If no rows are returned
        
        Example:
            user = session.query_one(
                "SELECT * FROM users WHERE id = $1",
                [user_id]
            )
        """
        return self._session.query_one(sql, params)
    
    def execute(
        self,
        sql: str,
        params: Optional[List[Any]] = None
    ) -> int:
        """
        Execute an INSERT, UPDATE, or DELETE query.
        
        Args:
            sql: SQL query with $1, $2, etc. placeholders
            params: List of parameter values
        
        Returns:
            Number of rows affected
        
        Example:
            affected = session.execute(
                "UPDATE users SET status = $1 WHERE id = $2",
                ["inactive", user_id]
            )
        """
        return self._session.execute(sql, params)
    
    def execute_many(
        self,
        sql: str,
        params_list: List[List[Any]]
    ) -> int:
        """
        Execute a batch of INSERT, UPDATE, or DELETE queries.
        
        Args:
            sql: SQL query with $1, $2, etc. placeholders
            params_list: List of parameter lists, one per execution
        
        Returns:
            Total number of rows affected
        
        Example:
            affected = session.execute_many(
                "INSERT INTO users (name, email) VALUES ($1, $2)",
                [
                    ["Alice", "alice@example.com"],
                    ["Bob", "bob@example.com"],
                ]
            )
        """
        return self._session.execute_many(sql, params_list)
    
    def set_auto_commit(self, auto_commit: bool) -> "DbSession":
        """
        Set whether to auto-commit the transaction on request end.
        
        Args:
            auto_commit: If True, commit on success; if False, rollback on success
        
        Returns:
            self for method chaining
        """
        self._session.set_auto_commit(auto_commit)
        return self
    
    def set_error(self) -> "DbSession":
        """
        Mark that an error occurred.
        
        This will cause the transaction to be rolled back on request end.
        
        Returns:
            self for method chaining
        """
        self._session.set_error()
        return self
    
    @property
    def state(self) -> str:
        """Get the current session state."""
        return self._session.state()
    
    @contextmanager
    def transaction(self):
        """
        Context manager for transaction handling.
        
        Automatically commits on success and rolls back on exception.
        
        Example:
            with session.transaction():
                session.execute("INSERT INTO users (name) VALUES ($1)", ["Alice"])
                session.execute("INSERT INTO logs (action) VALUES ($1)", ["user_created"])
        """
        self.begin()
        try:
            yield self
            self.commit()
        except Exception:
            self.rollback()
            raise
    
    def __repr__(self) -> str:
        return f"DbSession(request_id='{self.request_id}', state='{self.state}')"


def db(ctx_or_request_id: Union[str, Any], alias: str = "default") -> Union["DbSession", "AnySession"]:
    """
    Get a database session for the current request with the specified alias.
    
    For PostgreSQL databases, returns a ``DbSession``.
    For MySQL/SQLite databases, returns an ``AnySession``.
    
    Args:
        ctx_or_request_id: Either a Context object or a string request ID
        alias: Database alias to use (default: "default")
    
    Returns:
        DbSession (PostgreSQL) or AnySession (MySQL/SQLite)
    """
    Database._ensure_initialized(alias)
    
    config = Database._databases.get(alias, {})
    driver = config.get('driver', 'postgres')
    
    if driver != 'postgres':
        pool = Database._any_pools[alias]
        return AnySession(pool)
    
    if isinstance(ctx_or_request_id, str):
        request_id = ctx_or_request_id
    else:
        request_id = getattr(ctx_or_request_id, 'request_id', str(ctx_or_request_id))
    
    return DbSession(_get_db(request_id, alias))


def finalize_db(ctx_or_request_id: Union[str, Any], alias: Optional[str] = None) -> None:
    """
    Finalize the database session(s) for a request.
    
    This commits or rolls back any pending transaction and releases
    the connection back to the pool. Usually called automatically
    at the end of a request.
    
    Args:
        ctx_or_request_id: Either a Context object or request ID string
        alias: Database alias to finalize. If None, finalizes all databases for this request.
    """
    if isinstance(ctx_or_request_id, str):
        request_id = ctx_or_request_id
    else:
        request_id = getattr(ctx_or_request_id, 'request_id', str(ctx_or_request_id))
    
    if alias is None:
        # Finalize all databases for this request
        _finalize_db_all(request_id)
    else:
        # Finalize specific database
        _finalize_db(request_id, alias)



def _detect_driver(url: str) -> str:
    """Detect the database driver from the URL scheme."""
    lower = url.lower()
    if lower.startswith(("postgresql://", "postgres://")):
        return "postgres"
    if lower.startswith("mysql://"):
        return "mysql"
    if lower.startswith("sqlite:"):
        return "sqlite"
    raise ValueError(
        f"Unsupported database URL scheme: {url!r}. "
        "Supported: postgresql://, mysql://, sqlite://"
    )


class AnySession:
    """
    Database session for MySQL and SQLite databases (via sqlx Any driver).
    
    Provides a similar API to ``DbSession`` but backed by sqlx's ``AnyPool``.
    """

    def __init__(self, pool: "_AnyPool"):
        self._pool = pool

    def query(
        self,
        sql: str,
        params: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results as a list of dicts."""
        return self._pool.query(sql, params)

    def query_one(
        self,
        sql: str,
        params: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Execute a SELECT query and return a single result."""
        return self._pool.query_one(sql, params)

    def execute(
        self,
        sql: str,
        params: Optional[List[str]] = None,
    ) -> int:
        """Execute an INSERT/UPDATE/DELETE and return rows affected."""
        return self._pool.execute(sql, params)

    def __repr__(self) -> str:
        return f"AnySession({self._pool!r})"


@runtime_checkable
class TenantResolver(Protocol):
    """Protocol for resolving a tenant identifier from a request."""

    async def resolve(self, request: Any) -> str:
        """Return a tenant identifier (e.g. subdomain, JWT claim)."""
        ...


class MultiTenantDatabase:
    """
    Multi-tenant database routing with lazy pool-per-tenant.

    Each resolved tenant gets its own connection pool, initialised on first access.
    Pools are bounded by *max_tenants*; the least-recently-used pool is evicted
    when the limit is exceeded (connections are closed on eviction).

    Args:
        resolver: An object implementing the ``TenantResolver`` protocol.
        dsn_template: A DSN with ``{tenant}`` placeholder, e.g.
            ``"postgresql://user:pass@host:5432/{tenant}"``
        max_tenants: Maximum number of tenant pools to keep alive.
        pool_max_size: ``max_size`` passed to each tenant pool.

    Example::

        class SubdomainResolver:
            async def resolve(self, request) -> str:
                host = request.headers.get("host", "")
                return host.split(".")[0]

        mt = MultiTenantDatabase(
            resolver=SubdomainResolver(),
            dsn_template="postgresql://user:pass@localhost:5432/{tenant}",
            max_tenants=50,
        )

        @app.get("/data")
        async def get_data(req, res, ctx):
            session = await mt.session(req, ctx)
            rows = session.query("SELECT * FROM items")
            res.json(rows)
    """

    def __init__(
        self,
        resolver: TenantResolver,
        dsn_template: str,
        max_tenants: int = 100,
        pool_max_size: int = 8,
    ) -> None:
        if "{tenant}" not in dsn_template:
            raise ValueError("dsn_template must contain '{tenant}' placeholder")

        self._resolver = resolver
        self._dsn_template = dsn_template
        self._max_tenants = max_tenants
        self._pool_max_size = pool_max_size
        # OrderedDict is used as an LRU cache (move_to_end on access)
        self._tenants: OrderedDict[str, bool] = OrderedDict()

    def _ensure_tenant(self, tenant: str) -> None:
        """Configure + initialise the pool for *tenant* if not already done."""
        if tenant in self._tenants:
            # Mark as recently used
            self._tenants.move_to_end(tenant)
            return

        # Evict LRU tenant if at capacity
        while len(self._tenants) >= self._max_tenants:
            evicted, _ = self._tenants.popitem(last=False)
            alias = f"_mt_{evicted}"
            Database.close(alias)

        alias = f"_mt_{tenant}"
        dsn = self._dsn_template.replace("{tenant}", tenant)
        Database.configure(url=dsn, max_size=self._pool_max_size, alias=alias)
        Database._ensure_initialized(alias)
        self._tenants[tenant] = True

    async def session(self, request: Any, ctx_or_request_id: Any) -> "DbSession":
        """
        Resolve the tenant from *request* and return a ``DbSession``.

        Args:
            request: The incoming request object (passed to the resolver).
            ctx_or_request_id: A Context object or request-id string.

        Returns:
            A ``DbSession`` connected to the resolved tenant's database.
        """
        tenant = await self._resolver.resolve(request)
        self._ensure_tenant(tenant)
        alias = f"_mt_{tenant}"
        return db(ctx_or_request_id, alias=alias)

    def close_all(self) -> None:
        """Close all tenant pools."""
        for tenant in list(self._tenants):
            alias = f"_mt_{tenant}"
            Database.close(alias)
        self._tenants.clear()

__all__ = [
    "Database",
    "DbSession",
    "AnySession",
    "db",
    "finalize_db",
    "TenantResolver",
    "MultiTenantDatabase",
]
