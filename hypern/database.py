from typing import Any, Dict, List, Optional, Union
from contextlib import contextmanager

from hypern._hypern import (
    ConnectionPool as _ConnectionPool,
    PoolConfig as _PoolConfig,
    PoolStatus as _PoolStatus,
    DbSession as _DbSession,
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
    """
    
    _databases: Dict[str, Dict[str, Any]] = {}
    _initialized_pools: Dict[str, bool] = {}
    
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
            url: PostgreSQL connection URL (postgresql://user:pass@host:port/database)
            max_size: Maximum number of connections in the pool (default: 16)
            min_idle: Minimum idle connections to maintain (default: None)
            connect_timeout_secs: Connection timeout in seconds (default: 30)
            idle_timeout_secs: Idle connection timeout in seconds (default: None)
            max_lifetime_secs: Maximum connection lifetime in seconds (default: None)
            test_before_acquire: If True, test connections before acquiring them (re-ping pool) (default: False)
            keepalive_secs: TCP keepalive interval in seconds (default: None, disabled)
            alias: Database alias for identification (default: "default")
        
        Raises:
            RuntimeError: If database with this alias is already configured
        
        Example:
            Database.configure(
                url="postgresql://user:pass@localhost:5432/mydb",
                max_size=20,
                connect_timeout_secs=10,
                test_before_acquire=True,  # Verify connections before use
                keepalive_secs=60,         # Send TCP keepalive every 60 seconds
                alias="default"
            )
            
            Database.configure(
                url="postgresql://user:pass@localhost:5432/analytics",
                max_size=5,
                alias="analytics"
            )
        """
        if alias in cls._databases:
            raise RuntimeError(f"Database with alias '{alias}' already configured. Call Database.close('{alias}') first to reconfigure.")
        
        # Store config for lazy initialization (after fork)
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
        
        Note: After calling this, you must call configure() again before using the database.
        """
        if alias is None:
            # Close all databases
            _ConnectionPool.close_all()
            cls._databases.clear()
            cls._initialized_pools.clear()
        else:
            # Close specific database
            if alias in cls._databases:
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


def db(ctx_or_request_id: Union[str, Any], alias: str = "default") -> DbSession:
    """
    Get a database session for the current request with the specified alias.
    
    This is the primary way to access the database in request handlers.
    Each request gets exactly one connection from the pool per alias.
    
    Args:
        ctx_or_request_id: Either a Context object with request_id attribute,
                          or a string request ID directly
        alias: Database alias to use (default: "default")
    
    Returns:
        DbSession for the request
    
    Example:
        @app.get("/users")
        def get_users(req, res, ctx):
            # Default database
            session = db(ctx)
            users = session.query("SELECT * FROM users")
            
            # Analytics database
            analytics_session = db(ctx, alias="analytics")
            logs = analytics_session.query("SELECT * FROM logs")
            
            res.json({"users": users, "logs": logs})
    """
    # Ensure pool is initialized (lazy initialization after fork)
    Database._ensure_initialized(alias)
    
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


__all__ = [
    "Database",
    "DbSession",
    "db",
    "finalize_db",
]
