from __future__ import annotations

from sqlalchemy import String, type_coerce
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import UserDefinedType


class PointGeometry(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "geometry(POINT,4326)"

    def bind_expression(self, bindvalue):
        return _GeometryFromEWKT(type_coerce(bindvalue, String()))


class _GeometryFromEWKT(FunctionElement):
    type = PointGeometry()
    inherit_cache = True


@compiles(_GeometryFromEWKT, "postgresql")
def _compile_geometry_from_ewkt_postgresql(element, compiler, **kw) -> str:
    expression = compiler.process(list(element.clauses)[0], **kw)
    return f"ST_GeomFromEWKT({expression})"


@compiles(_GeometryFromEWKT, "sqlite")
def _compile_geometry_from_ewkt_sqlite(element, compiler, **kw) -> str:
    return compiler.process(list(element.clauses)[0], **kw)


@compiles(PointGeometry, "sqlite")
def _compile_point_geometry_sqlite(type_, compiler, **kw) -> str:
    return "TEXT"


def point_wkt(latitude: float | None, longitude: float | None) -> str | None:
    if latitude is None or longitude is None:
        return None
    return f"SRID=4326;POINT({longitude} {latitude})"
