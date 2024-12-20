# -*- coding: utf-8 -*-
from typing import List, TypedDict

from uuid import uuid4
from mongoengine import connect


class TypedDictModel(TypedDict):
    host: str
    alias: str


class NoSqlConfig:
    def __init__(self, dbs_config: List[TypedDictModel]):
        self.dbs_config = dbs_config

    def _connect_db(self, db_config: TypedDictModel):
        _alias = db_config.get("alias", str(uuid4()))
        connect(host=db_config["host"], alias=_alias)

    def init_app(self, app):
        self.app = app  # noqa
        # connect
        for db_config in self.dbs_config:
            self._connect_db(db_config)
