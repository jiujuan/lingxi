from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator, UserDefinedType


class PgVector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def get_col_spec(self, **_kw) -> str:
        return f"vector({self.dimension})"


class EmbeddingVector(TypeDecorator):
    impl = JSON
    cache_ok = True

    def __init__(self, dimension: int) -> None:
        super().__init__()
        self.dimension = dimension

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PgVector(self.dimension))
        return dialect.type_descriptor(JSON())

