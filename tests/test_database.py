"""
Comprehensive tests for the Database feature.

Tests cover:
- Connection pool initialization and management
- Request-scoped database sessions
- Transaction management (commit/rollback)
- CRUD operations with real database
- Error handling and edge cases
- Concurrent request handling
"""

import pytest
import threading
import json
import uuid as uuid_module

# Import from hypern
from hypern.database import Database, db, finalize_db
from hypern._hypern import ConnectionPool, PoolConfig


# Override the autouse fixture to not use the test server
@pytest.fixture(autouse=True)
def reset_database():
    """Override the default reset_database fixture to do nothing for database tests."""
    yield


# Test database configuration
TEST_DB_URL = "postgresql://nghiem:nghiem@localhost:5432/test"


@pytest.fixture(scope="module")
def setup_database():
    """Initialize the database pool and create test tables."""
    # Initialize the connection pool
    config = PoolConfig(
        url=TEST_DB_URL,
        max_size=10,
        min_idle=2,
        connect_timeout_secs=30,
    )
    try:
        ConnectionPool.initialize(config)
    except RuntimeError:
        # Pool already initialized, that's OK
        pass
    
    # Create test tables
    session = db("setup")
    try:
        # Drop tables if they exist (autocommit mode)
        session.execute("DROP TABLE IF EXISTS test_items CASCADE")
        session.execute("DROP TABLE IF EXISTS test_users CASCADE")
        session.execute("DROP TABLE IF EXISTS test_orders CASCADE")
        
        # Create test_users table
        session.execute("""
            CREATE TABLE test_users (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                age INTEGER,
                active BOOLEAN DEFAULT true,
                balance NUMERIC(10, 2) DEFAULT 0.00,
                metadata JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create test_items table
        # Note: Using uuid_generate_v4() requires uuid-ossp extension
        # For simplicity, we'll just use TEXT for uuid field in tests
        session.execute("""
            CREATE TABLE test_items (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES test_users(id) ON DELETE CASCADE,
                name VARCHAR(100) NOT NULL,
                price NUMERIC(10, 2) NOT NULL,
                quantity INTEGER DEFAULT 1,
                uuid UUID
            )
        """)
        
        # Create test_orders table for transaction tests
        session.execute("""
            CREATE TABLE test_orders (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES test_users(id),
                total NUMERIC(10, 2) NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # DDL statements are auto-committed in PostgreSQL
    except Exception as e:
        raise e
    finally:
        finalize_db("setup")
    
    yield
    
    # Cleanup after all tests
    session = db("cleanup")
    try:
        session.execute("DROP TABLE IF EXISTS test_items CASCADE")
        session.execute("DROP TABLE IF EXISTS test_users CASCADE")
        session.execute("DROP TABLE IF EXISTS test_orders CASCADE")
        # DDL statements are auto-committed
    except Exception:
        pass
    finally:
        finalize_db("cleanup")


class TestConnectionPool:
    """Tests for connection pool management."""
    
    def test_pool_status(self, setup_database):
        """Test getting pool status."""
        status = ConnectionPool.status()
        assert status is not None
        assert hasattr(status, 'size')
        assert hasattr(status, 'available')
        assert hasattr(status, 'max_size')
    
    def test_pool_is_initialized(self, setup_database):
        """Test that pool is initialized."""
        assert ConnectionPool.is_initialized() is True


class TestDbSession:
    """Tests for database session management."""
    
    def test_session_creation_and_release(self, setup_database):
        """Test creating and releasing a database session."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        assert session is not None
        
        # Execute a simple query
        result = session.query("SELECT 1 as value")
        assert len(result) == 1
        assert result[0]["value"] == 1
        
        # Release the session
        finalize_db(request_id)
    
    def test_same_session_per_request(self, setup_database):
        """Test that the same request ID returns the same session."""
        request_id = f"test-{uuid_module.uuid4()}"
        session1 = db(request_id)
        session2 = db(request_id)
        
        # Should have the same request_id
        assert session1.request_id == session2.request_id
        
        finalize_db(request_id)
    
    def test_different_sessions_per_request(self, setup_database):
        """Test that different request IDs get different sessions."""
        request_id1 = f"test-{uuid_module.uuid4()}"
        request_id2 = f"test-{uuid_module.uuid4()}"
        
        session1 = db(request_id1)
        session2 = db(request_id2)
        
        # Should be different session objects
        assert session1.request_id != session2.request_id
        
        finalize_db(request_id1)
        finalize_db(request_id2)


class TestCRUDOperations:
    """Tests for CRUD operations with real database."""
    
    def test_insert_and_select(self, setup_database):
        """Test inserting and selecting data."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"alice-{uuid_module.uuid4()}@test.com"
        
        try:
            # Start transaction
            session.begin()
            
            # Insert a user
            session.execute(
                "INSERT INTO test_users (name, email, age) VALUES ($1, $2, $3)",
                ["Alice", unique_email, 30]
            )
            session.commit()
            
            # Select the user
            users = session.query(
                "SELECT name, age FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert len(users) == 1
            assert users[0]["name"] == "Alice"
            assert users[0]["age"] == 30
        finally:
            finalize_db(request_id)
    
    def test_update_operation(self, setup_database):
        """Test updating data."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"bob-{uuid_module.uuid4()}@test.com"
        
        try:
            session.begin()
            
            # Insert a user
            session.execute(
                "INSERT INTO test_users (name, email, age) VALUES ($1, $2, $3)",
                ["Bob", unique_email, 25]
            )
            session.commit()
            
            session.begin()
            # Update the user
            session.execute(
                "UPDATE test_users SET age = $1 WHERE email = $2",
                [26, unique_email]
            )
            session.commit()
            
            # Verify the update
            users = session.query(
                "SELECT age FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert users[0]["age"] == 26
        finally:
            finalize_db(request_id)
    
    def test_delete_operation(self, setup_database):
        """Test deleting data."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"charlie-{uuid_module.uuid4()}@test.com"
        
        try:
            session.begin()
            
            # Insert a user
            session.execute(
                "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                ["Charlie", unique_email]
            )
            session.commit()
            
            session.begin()
            # Delete the user
            session.execute(
                "DELETE FROM test_users WHERE email = $1",
                [unique_email]
            )
            session.commit()
            
            # Verify deletion
            users = session.query(
                "SELECT * FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert len(users) == 0
        finally:
            finalize_db(request_id)
    
    def test_query_one(self, setup_database):
        """Test fetching a single row."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"diana-{uuid_module.uuid4()}@test.com"
        
        try:
            session.begin()
            
            # Insert a user
            session.execute(
                "INSERT INTO test_users (name, email, age) VALUES ($1, $2, $3)",
                ["Diana", unique_email, 28]
            )
            session.commit()
            
            # Fetch one
            user = session.query_one(
                "SELECT name, email, age FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert user is not None
            assert user["name"] == "Diana"
            assert user["email"] == unique_email
            assert user["age"] == 28
        finally:
            finalize_db(request_id)
    
    def test_query_one_no_result(self, setup_database):
        """Test fetching when no rows exist raises error."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        
        try:
            with pytest.raises(RuntimeError, match="No rows returned"):
                session.query_one(
                    "SELECT * FROM test_users WHERE email = $1",
                    ["nonexistent@test.com"]
                )
        finally:
            finalize_db(request_id)


class TestTransactions:
    """Tests for transaction management."""
    
    def test_commit_transaction(self, setup_database):
        """Test that committed transactions persist data."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"commit-{uuid_module.uuid4()}@test.com"
        
        try:
            # Start transaction and insert
            session.begin()
            session.execute(
                "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                ["CommitUser", unique_email]
            )
            session.commit()
        finally:
            finalize_db(request_id)
        
        # Verify in a new session
        request_id2 = f"test-{uuid_module.uuid4()}"
        session2 = db(request_id2)
        try:
            users = session2.query(
                "SELECT * FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert len(users) == 1
            assert users[0]["name"] == "CommitUser"
        finally:
            finalize_db(request_id2)
    
    def test_rollback_transaction(self, setup_database):
        """Test that rolled back transactions don't persist data."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"rollback-{uuid_module.uuid4()}@test.com"
        
        try:
            # Start transaction and insert
            session.begin()
            session.execute(
                "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                ["RollbackUser", unique_email]
            )
            # Rollback instead of commit
            session.rollback()
        finally:
            finalize_db(request_id)
        
        # Verify in a new session - data should NOT exist
        request_id2 = f"test-{uuid_module.uuid4()}"
        session2 = db(request_id2)
        try:
            users = session2.query(
                "SELECT * FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert len(users) == 0
        finally:
            finalize_db(request_id2)
    
    def test_multiple_operations_in_transaction(self, setup_database):
        """Test multiple operations in a single transaction."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"multi-{uuid_module.uuid4()}@test.com"
        
        try:
            session.begin()
            
            # Insert user
            session.execute(
                "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                ["MultiUser", unique_email]
            )
            
            # Get user ID
            user = session.query_one(
                "SELECT id FROM test_users WHERE email = $1",
                [unique_email]
            )
            user_id = user["id"]
            
            # Insert related item
            session.execute(
                "INSERT INTO test_items (user_id, name, price) VALUES ($1, $2, $3)",
                [user_id, "Test Item", 99.99]
            )
            
            session.commit()
            
            # Verify both records exist
            items = session.query(
                "SELECT i.name, i.price FROM test_items i JOIN test_users u ON i.user_id = u.id WHERE u.email = $1",
                [unique_email]
            )
            assert len(items) == 1
            assert items[0]["name"] == "Test Item"
        finally:
            finalize_db(request_id)
    
    def test_transaction_context_manager(self, setup_database):
        """Test transaction context manager."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"ctx-{uuid_module.uuid4()}@test.com"
        
        try:
            with session.transaction():
                session.execute(
                    "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                    ["CtxUser", unique_email]
                )
            
            # Verify data persisted
            users = session.query(
                "SELECT * FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert len(users) == 1
        finally:
            finalize_db(request_id)
    
    def test_transaction_context_manager_rollback_on_error(self, setup_database):
        """Test transaction context manager rolls back on error."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"ctx-err-{uuid_module.uuid4()}@test.com"
        
        try:
            try:
                with session.transaction():
                    session.execute(
                        "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                        ["CtxErrUser", unique_email]
                    )
                    raise ValueError("Simulated error")
            except ValueError:
                pass  # Expected
            
            # Verify data was NOT persisted
            users = session.query(
                "SELECT * FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert len(users) == 0
        finally:
            finalize_db(request_id)


class TestDataTypes:
    """Tests for various PostgreSQL data types."""
    
    def test_numeric_types(self, setup_database):
        """Test numeric data types."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"numeric-{uuid_module.uuid4()}@test.com"
        
        try:
            session.begin()
            session.execute(
                "INSERT INTO test_users (name, email, age, balance) VALUES ($1, $2, $3, $4)",
                ["NumericUser", unique_email, 35, 1234.56]
            )
            session.commit()
            
            user = session.query_one(
                "SELECT age, balance FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert user["age"] == 35
            # balance is NUMERIC, may come back as Decimal or float
            assert float(str(user["balance"])) == pytest.approx(1234.56)
        finally:
            finalize_db(request_id)
    
    def test_boolean_type(self, setup_database):
        """Test boolean data type."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"bool-{uuid_module.uuid4()}@test.com"
        
        try:
            session.begin()
            session.execute(
                "INSERT INTO test_users (name, email, active) VALUES ($1, $2, $3)",
                ["BoolUser", unique_email, False]
            )
            session.commit()
            
            user = session.query_one(
                "SELECT active FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert user["active"] is False
        finally:
            finalize_db(request_id)
    
    def test_json_type(self, setup_database):
        """Test JSONB data type."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"json-{uuid_module.uuid4()}@test.com"
        metadata = {"role": "admin", "permissions": ["read", "write"], "settings": {"theme": "dark"}}
        
        try:
            session.begin()
            # Pass the dict directly - our framework handles JSON conversion
            session.execute(
                "INSERT INTO test_users (name, email, metadata) VALUES ($1, $2, $3)",
                ["JsonUser", unique_email, metadata]
            )
            session.commit()
            
            user = session.query_one(
                "SELECT metadata FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert user["metadata"] is not None
            # metadata should be a dict
            if isinstance(user["metadata"], str):
                result_meta = json.loads(user["metadata"])
            else:
                result_meta = user["metadata"]
            assert result_meta["role"] == "admin"
            assert "read" in result_meta["permissions"]
        finally:
            finalize_db(request_id)
    
    def test_timestamp_type(self, setup_database):
        """Test timestamp data type."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"ts-{uuid_module.uuid4()}@test.com"
        
        try:
            session.begin()
            session.execute(
                "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                ["TimestampUser", unique_email]
            )
            session.commit()
            
            user = session.query_one(
                "SELECT created_at FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert user["created_at"] is not None
        finally:
            finalize_db(request_id)
    
    def test_null_values(self, setup_database):
        """Test NULL values."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"null-{uuid_module.uuid4()}@test.com"
        
        try:
            session.begin()
            session.execute(
                "INSERT INTO test_users (name, email, age, metadata) VALUES ($1, $2, $3, $4)",
                ["NullUser", unique_email, None, None]
            )
            session.commit()
            
            user = session.query_one(
                "SELECT age, metadata FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert user["age"] is None
            assert user["metadata"] is None
        finally:
            finalize_db(request_id)


class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_empty_result_set(self, setup_database):
        """Test handling empty result sets."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        
        try:
            results = session.query(
                "SELECT * FROM test_users WHERE email = $1",
                ["definitely-does-not-exist@test.com"]
            )
            assert results == []
        finally:
            finalize_db(request_id)
    
    def test_special_characters_in_data(self, setup_database):
        """Test handling special characters."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"special-{uuid_module.uuid4()}@test.com"
        special_name = "O'Brien \"The\" <Test> User; DROP TABLE"
        
        try:
            session.begin()
            session.execute(
                "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                [special_name, unique_email]
            )
            session.commit()
            
            user = session.query_one(
                "SELECT name FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert user["name"] == special_name
        finally:
            finalize_db(request_id)
    
    def test_large_text_data(self, setup_database):
        """Test handling large text data."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"large-{uuid_module.uuid4()}@test.com"
        large_name = "A" * 100  # Max VARCHAR length
        
        try:
            session.begin()
            session.execute(
                "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                [large_name, unique_email]
            )
            session.commit()
            
            user = session.query_one(
                "SELECT name FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert user["name"] == large_name
        finally:
            finalize_db(request_id)
    
    def test_sql_injection_prevention(self, setup_database):
        """Test that SQL injection is prevented via parameterized queries."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        
        try:
            # This should be safely escaped
            malicious_email = "'; DROP TABLE test_users; --"
            
            # This should NOT drop the table
            results = session.query(
                "SELECT * FROM test_users WHERE email = $1",
                [malicious_email]
            )
            
            # Table should still exist
            table_check = session.query(
                "SELECT table_name FROM information_schema.tables WHERE table_name = 'test_users'"
            )
            assert len(table_check) == 1
        finally:
            finalize_db(request_id)
    
    def test_constraint_violation_error(self, setup_database):
        """Test handling constraint violation errors."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        unique_email = f"constraint-{uuid_module.uuid4()}@test.com"
        
        try:
            # Insert first user
            session.begin()
            session.execute(
                "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                ["User1", unique_email]
            )
            session.commit()
            
            # Try to insert duplicate email
            session.begin()
            with pytest.raises(RuntimeError):
                session.execute(
                    "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                    ["User2", unique_email]
                )
        finally:
            finalize_db(request_id)
    
    def test_begin_twice_raises_error(self, setup_database):
        """Test that calling begin twice raises an error."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        
        try:
            session.begin()
            with pytest.raises(RuntimeError):
                session.begin()
            session.rollback()
        finally:
            finalize_db(request_id)
    
    def test_commit_without_transaction_raises_error(self, setup_database):
        """Test that commit without transaction raises an error."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        
        try:
            with pytest.raises(RuntimeError):
                session.commit()
        finally:
            finalize_db(request_id)
    
    def test_rollback_without_transaction_raises_error(self, setup_database):
        """Test that rollback without transaction raises an error."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        
        try:
            with pytest.raises(RuntimeError):
                session.rollback()
        finally:
            finalize_db(request_id)


class TestExecuteMany:
    """Tests for batch execution."""
    
    def test_execute_many_basic(self, setup_database):
        """Test batch insert with execute_many."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        
        try:
            session.begin()
            
            # Batch insert users
            affected = session.execute_many(
                "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                [
                    ["Batch1", f"batch1-{uuid_module.uuid4()}@test.com"],
                    ["Batch2", f"batch2-{uuid_module.uuid4()}@test.com"],
                    ["Batch3", f"batch3-{uuid_module.uuid4()}@test.com"],
                ]
            )
            session.commit()
            
            assert affected == 3
        finally:
            finalize_db(request_id)


class TestConcurrentRequests:
    """Tests for concurrent request handling."""
    
    def test_concurrent_sessions(self, setup_database):
        """Test multiple concurrent sessions using threads."""
        results = []
        errors = []
        
        def insert_user(index: int):
            request_id = f"concurrent-{index}-{uuid_module.uuid4()}"
            try:
                session = db(request_id)
                unique_email = f"concurrent-{index}-{uuid_module.uuid4()}@test.com"
                
                session.begin()
                session.execute(
                    "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                    [f"ConcurrentUser{index}", unique_email]
                )
                session.commit()
                results.append(unique_email)
            except Exception as e:
                errors.append((index, str(e)))
            finally:
                finalize_db(request_id)
        
        # Run 10 concurrent inserts using threads
        threads = []
        for i in range(10):
            t = threading.Thread(target=insert_user, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Check for errors
        assert len(errors) == 0, f"Errors occurred: {errors}"
        
        # Verify all users were created
        request_id = f"verify-{uuid_module.uuid4()}"
        session = db(request_id)
        try:
            for email in results:
                users = session.query(
                    "SELECT * FROM test_users WHERE email = $1",
                    [email]
                )
                assert len(users) == 1
        finally:
            finalize_db(request_id)


class TestSessionState:
    """Tests for session state tracking."""
    
    def test_session_state_transitions(self, setup_database):
        """Test session state transitions."""
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        
        try:
            # Initial state after getting connection
            session.query("SELECT 1")  # Force connection
            
            # Begin transaction
            session.begin()
            
            # Commit
            session.commit()
            
            # Can begin another transaction
            session.begin()
            session.rollback()
        finally:
            finalize_db(request_id)


class TestAutoCommit:
    """Tests for auto-commit behavior."""
    
    def test_auto_commit_on_finalize(self, setup_database):
        """Test that auto-commit commits on finalize."""
        unique_email = f"auto-commit-{uuid_module.uuid4()}@test.com"
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        
        try:
            session.begin()
            session.execute(
                "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                ["AutoCommitUser", unique_email]
            )
            # Don't call commit, let finalize do it
        finally:
            finalize_db(request_id)
        
        # Verify data was committed
        request_id2 = f"verify-{uuid_module.uuid4()}"
        session2 = db(request_id2)
        try:
            users = session2.query(
                "SELECT * FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert len(users) == 1
        finally:
            finalize_db(request_id2)
    
    def test_set_auto_commit_false(self, setup_database):
        """Test setting auto-commit to False causes rollback."""
        unique_email = f"no-auto-commit-{uuid_module.uuid4()}@test.com"
        request_id = f"test-{uuid_module.uuid4()}"
        session = db(request_id)
        
        try:
            session.set_auto_commit(False)
            session.begin()
            session.execute(
                "INSERT INTO test_users (name, email) VALUES ($1, $2)",
                ["NoAutoCommitUser", unique_email]
            )
            # Don't call commit, with auto_commit=False, finalize should rollback
        finally:
            finalize_db(request_id)
        
        # Verify data was NOT committed
        request_id2 = f"verify-{uuid_module.uuid4()}"
        session2 = db(request_id2)
        try:
            users = session2.query(
                "SELECT * FROM test_users WHERE email = $1",
                [unique_email]
            )
            assert len(users) == 0
        finally:
            finalize_db(request_id2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
