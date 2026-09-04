"""Base models shared across the domain."""

import uuid

from django.db import models


class TimestampedModel(models.Model):
    """
    Adds creation and update timestamps.

    Every row in Aviro answers a question about the past, so knowing when a
    record appeared and when it last moved is worth the two columns.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """
    Public-facing identifier.

    Sequential integer ids would leak how many farms and batches exist, and
    would let one farmer guess another's URLs. UUIDs cost a little space and
    remove both problems.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimestampedModel):
    """The default base for domain models: UUID primary key plus timestamps."""

    class Meta:
        abstract = True
