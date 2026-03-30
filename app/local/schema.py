"""Local schema module — re-exports common schema helpers."""

from app.common.schema import _simplify_skill_schema, schema_router

__all__ = ["schema_router", "_simplify_skill_schema"]
