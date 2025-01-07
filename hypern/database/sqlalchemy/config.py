# -*- coding: utf-8 -*-
import asyncio
import traceback
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_scoped_session
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.expression import Delete, Insert, Update


class SqlalchemyConfig:
    def __init__(self, default_engine: AsyncEngine | None = None, reader_engine: AsyncEngine | None = None, writer_engine: AsyncEngine | None = None):
        """
        Initialize the SQL configuration.
        You can provide a default engine, a reader engine, and a writer engine.
        If only one engine is provided (default_engine), it will be used for both reading and writing.
        If both reader and writer engines are provided, they will be used for reading and writing respectively.
        Note: The reader and writer engines must be different.
        """

        assert default_engine or reader_engine or writer_engine, "At least one engine must be provided."
        assert not (reader_engine and writer_engine and id(reader_engine) == id(writer_engine)), "Reader and writer engines must be different."

        engines = {
            "writer": writer_engine or default_engine,
            "reader": reader_engine or default_engine,
        }

        class RoutingSession(Session):
            def get_bind(this, mapper=None, clause=None, **kwargs):
                if this._flushing or isinstance(clause, (Update, Delete, Insert)):
                    return engines["writer"].sync_engine
                return engines["reader"].sync_engine

        async_session_factory = sessionmaker(
            class_=AsyncSession,
            sync_session_class=RoutingSession,
            expire_on_commit=False,
        )

        session_scope: AsyncSession | async_scoped_session = async_scoped_session(
            session_factory=async_session_factory,
            scopefunc=asyncio.current_task,
        )

        @asynccontextmanager
        async def get_session():
            """
            Get the database session.
            This can be used for dependency injection.

            :return: The database session.
            """
            try:
                yield session_scope
            except Exception:
                traceback.print_exc()
                await session_scope.rollback()
            finally:
                await session_scope.remove()
                await session_scope.close()

        self.get_session = get_session

    def init_app(self, app):
        app.inject("get_session", self.get_session)
