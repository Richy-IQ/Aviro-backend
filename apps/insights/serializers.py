from rest_framework import serializers


class CostLineSerializer(serializers.Serializer):
    category = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    pct_of_revenue = serializers.DecimalField(max_digits=6, decimal_places=1)


class CycleReportSerializer(serializers.Serializer):
    """One cycle, stated the way an income statement states it."""

    batch_id = serializers.CharField()
    name = serializers.CharField()
    breed = serializers.CharField()
    bird_type = serializers.CharField()

    started_on = serializers.DateField()
    closed_on = serializers.DateField(allow_null=True)
    days = serializers.IntegerField()
    # False means the figures are a projection, not money received. The client
    # must label it, so a lender cannot read it as booked income.
    is_closed = serializers.BooleanField()

    stocked = serializers.IntegerField()
    sold = serializers.IntegerField()
    mortality_pct = serializers.DecimalField(max_digits=5, decimal_places=1)
    average_weight_kg = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    feed_conversion = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)

    revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    costs = CostLineSerializer(many=True)
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    gross_profit = serializers.DecimalField(max_digits=14, decimal_places=2)
    margin = serializers.DecimalField(max_digits=6, decimal_places=1)

    cost_per_bird = serializers.DecimalField(max_digits=12, decimal_places=2)
    revenue_per_bird = serializers.DecimalField(max_digits=12, decimal_places=2)
    profit_per_bird = serializers.DecimalField(max_digits=12, decimal_places=2)
    cost_per_kg = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    price_per_kg = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)

    insights = serializers.ListField(child=serializers.CharField())


class BatchLineSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    bird_type = serializers.CharField()
    day = serializers.IntegerField()
    birds_alive = serializers.IntegerField()
    deaths = serializers.IntegerField()
    feed_kg = serializers.DecimalField(max_digits=12, decimal_places=1)
    days_logged = serializers.IntegerField()


class UpcomingSerializer(serializers.Serializer):
    batch_name = serializers.CharField()
    day = serializers.IntegerField()
    due_on = serializers.DateField()
    what = serializers.CharField()


class PeriodReportSerializer(serializers.Serializer):
    """The farm over the last week or month, against the window before it."""

    period = serializers.CharField()
    label = serializers.CharField()
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    days = serializers.IntegerField()

    days_logged = serializers.IntegerField()
    days_possible = serializers.IntegerField()
    active_batches = serializers.IntegerField()
    birds_alive = serializers.IntegerField()

    deaths = serializers.IntegerField()
    deaths_before = serializers.IntegerField()

    feed_kg = serializers.DecimalField(max_digits=12, decimal_places=1)
    feed_bags = serializers.DecimalField(max_digits=10, decimal_places=1)
    feed_before_kg = serializers.DecimalField(max_digits=12, decimal_places=1)

    recorded_spend = serializers.DecimalField(max_digits=14, decimal_places=2)
    revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    feed_cost_recorded = serializers.BooleanField()

    batches = BatchLineSerializer(many=True)
    upcoming = UpcomingSerializer(many=True)
    headline = serializers.CharField()
    notes = serializers.ListField(child=serializers.CharField())
