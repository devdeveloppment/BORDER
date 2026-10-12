"""Pagination par page, bornée (P2.8, ADR 0010 ; contrat P1 ``Paginated<T>``).

- ``page`` ≥ 1 et ``page_size`` entre 1 et ``MAX_PAGE_SIZE`` (défaut 50, comme le frontend P1) ;
- profondeur bornée : ``page * page_size`` ≤ ``MAX_DEPTH`` (au-delà, filtrer par période) — pas de parcours
  arbitraire coûteux ;
- une page au-delà de la dernière renvoie une liste vide (``count`` reste exact) ;
- paramètre invalide : 400 avec l'erreur par champ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rest_framework import serializers

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
MAX_DEPTH = 10_000


class PageQuerySerializer(serializers.Serializer[Any]):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=MAX_PAGE_SIZE, default=DEFAULT_PAGE_SIZE)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["page"] * attrs["page_size"] > MAX_DEPTH:
            raise serializers.ValidationError(
                {"page": [f"Au-delà des {MAX_DEPTH} premiers résultats : affiner les filtres (période)."]}
            )
        return attrs


@dataclass(frozen=True, slots=True)
class Page:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    def body(self, count: int, results: list[Any]) -> dict[str, Any]:
        return {"count": count, "page": self.page, "page_size": self.page_size, "results": results}


def page_from(query: Any) -> Page:
    serializer = PageQuerySerializer(data={k: query[k] for k in ("page", "page_size") if k in query})
    serializer.is_valid(raise_exception=True)
    return Page(serializer.validated_data["page"], serializer.validated_data["page_size"])


def paginated_serializer(
    name: str, item: serializers.Serializer[Any] | type[serializers.Serializer[Any]]
) -> Any:
    """Schéma OpenAPI ``Paginated<T>``."""
    return type(
        name,
        (serializers.Serializer,),
        {
            "count": serializers.IntegerField(),
            "page": serializers.IntegerField(),
            "page_size": serializers.IntegerField(),
            "results": item(many=True) if isinstance(item, type) else item,
        },
    )
