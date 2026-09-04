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
