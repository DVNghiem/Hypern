# -*- coding: utf-8 -*-

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR


class TSVector(sa.types.TypeDecorator):
    """
    .. _TSVECTOR:
    https://docs.sqlalchemy.org/en/latest/dialects/postgresql.html#full-text-search


    class IndexModel(Model):
        ....
        search_vector = Column(
            TSVector(),
            Computed(
                "to_tsvector('english', some_text|| ' ' ||some_text)",
                persisted=True,
            ),
        )
    session.query(IndexModel).filter(IndexModel.search_vector.match('foo'))

    session.query(IndexModel).filter(
        (IndexModel.name_vector | IndexModel.content_vector).match('foo')
    )

    """

    impl = TSVECTOR
    cache_ok = True

    class comparator_factory(TSVECTOR.Comparator):
        def match(self, other, **kwargs):
            if "postgresql_regconfig" not in kwargs:
                if "regconfig" in self.type.options:
                    kwargs["postgresql_regconfig"] = self.type.options["regconfig"]
            return TSVECTOR.Comparator.match(self, other, **kwargs)

        def __or__(self, other):
            return self.op("||")(other)

    def __init__(self, *args, **kwargs):
        self.columns = args
        self.options = kwargs
        super(TSVector, self).__init__()
