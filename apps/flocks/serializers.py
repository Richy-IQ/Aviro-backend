from __future__ import annotations

from rest_framework import serializers

from .models import Batch, BirdType, Breed, DailyLog, Sale, VaccinationSchedule


class BirdTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BirdType
        fields = ["id", "code", "label", "description", "cycle_days", "cycle_goal"]


class BreedSerializer(serializers.ModelSerializer):
    bird_type = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = Breed
        fields = ["id", "name", "bird_type"]


class VaccinationScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = VaccinationSchedule
        fields = ["id", "day", "name", "route", "notes"]


class BatchSerializer(serializers.ModelSerializer):
    bird_type = serializers.SlugRelatedField(
        slug_field="code", queryset=BirdType.objects.all()
    )
    breed_name = serializers.CharField(source="breed.name", read_only=True)
    pen_name = serializers.CharField(source="pen.name", read_only=True, default=None)

    class Meta:
        model = Batch
        fields = [
            "id", "name", "farm", "pen", "pen_name",
            "bird_type", "breed", "breed_name",
            "started_on", "stocked", "cost_per_bird", "transport_cost", "supplier",
            "status", "closed_on", "created_at",
        ]
        read_only_fields = ["farm", "status", "closed_on", "created_at"]


class MetricsSerializer(serializers.Serializer):
    """
    Derived figures. Read-only by definition — these are computed from the logs,
    never submitted.
    """

    day_in_cycle = serializers.IntegerField()
    cycle_days = serializers.IntegerField()
    alive = serializers.IntegerField()
    deaths = serializers.IntegerField()
    mortality_pct = serializers.DecimalField(max_digits=5, decimal_places=1)
    total_feed_kg = serializers.DecimalField(max_digits=10, decimal_places=1)
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    cost_per_bird = serializers.DecimalField(max_digits=10, decimal_places=2)
    earning_birds = serializers.IntegerField()
    average_weight_kg = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    feed_conversion = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    projected_revenue = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    projected_profit = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    optimal_sell_day = serializers.IntegerField(allow_null=True)
    sell_window_peaks = serializers.BooleanField()
    logged_today = serializers.BooleanField()
    streak_days = serializers.IntegerField()
    sell_window = serializers.SerializerMethodField()

    def get_sell_window(self, obj) -> list[dict]:
        return [
            {
                "day": point.day,
                "weight_kg": str(point.weight_kg),
                "projected_profit": str(point.projected_profit),
            }
            for point in obj.sell_window
        ]


class DailyLogSerializer(serializers.ModelSerializer):
    day_in_cycle = serializers.IntegerField(read_only=True)
    total_cost = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = DailyLog
        fields = [
            "id", "batch", "logged_on", "day_in_cycle",
            "feed_kg", "deaths", "death_cause", "health_activity",
            "feed_cost", "meds_cost", "other_cost", "total_cost",
            "note", "created_at",
        ]
        read_only_fields = ["batch", "created_at"]

    def validate_logged_on(self, value):
        batch = self.context["batch"]
        if value < batch.started_on:
            raise serializers.ValidationError(
                f"{batch.name} did not start until {batch.started_on}."
            )
        return value


class SaleSerializer(serializers.ModelSerializer):
    price_per_kg = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, allow_null=True
    )

    class Meta:
        model = Sale
        fields = [
            "id", "batch", "sold_on", "kind", "birds",
            "average_weight_kg", "revenue", "price_per_kg",
            "buyer_type", "buyer_name", "note", "created_at",
        ]
        read_only_fields = ["batch", "created_at"]
