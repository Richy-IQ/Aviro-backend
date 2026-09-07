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


class StatementLineSerializer(serializers.Serializer):
    label = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    pct_of_revenue = serializers.DecimalField(max_digits=6, decimal_places=1)


class BatchInPeriodSerializer(serializers.Serializer):
    name = serializers.CharField()
    bird_type = serializers.CharField()
    started_on = serializers.DateField()
    stocked = serializers.IntegerField()
    sold = serializers.IntegerField()
    status = serializers.CharField()


class IncomeStatementSerializer(serializers.Serializer):
    """A cash-basis income statement for a calendar period."""

    farm_name = serializers.CharField()
    farm_location = serializers.CharField(allow_blank=True)
    prepared_on = serializers.DateField()
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()

    revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    revenue_lines = StatementLineSerializer(many=True)

    cost_lines = StatementLineSerializer(many=True)
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=2)

    gross_profit = serializers.DecimalField(max_digits=14, decimal_places=2)
    margin = serializers.DecimalField(max_digits=6, decimal_places=1)

    birds_sold = serializers.IntegerField()
    kg_sold = serializers.DecimalField(max_digits=12, decimal_places=1)
    revenue_per_bird = serializers.DecimalField(max_digits=12, decimal_places=2)
    cost_per_bird = serializers.DecimalField(max_digits=12, decimal_places=2)
    profit_per_bird = serializers.DecimalField(max_digits=12, decimal_places=2)
    price_per_kg = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)

    days_in_period = serializers.IntegerField()
    days_logged = serializers.IntegerField()
    feed_cost_recorded = serializers.BooleanField()

    batches = BatchInPeriodSerializer(many=True)
    # Said on the face of the statement, because a lender reading it is
    # entitled to know how it was put together.
    basis = serializers.ListField(child=serializers.CharField())
    limitations = serializers.ListField(child=serializers.CharField())


class NetworkFarmRowSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    location = serializers.CharField(allow_blank=True)

    active_batches = serializers.IntegerField()
    birds_alive = serializers.IntegerField()

    days_logged = serializers.IntegerField()
    days_possible = serializers.IntegerField()
    last_logged_on = serializers.DateField(allow_null=True)
    days_silent = serializers.IntegerField(allow_null=True)

    deaths = serializers.IntegerField()
    deaths_before = serializers.IntegerField()
    feed_kg = serializers.DecimalField(max_digits=12, decimal_places=1)
    weight_vs_target_pct = serializers.DecimalField(
        max_digits=6, decimal_places=1, allow_null=True
    )

    status = serializers.CharField()
    attention = serializers.ListField(child=serializers.CharField())


class NetworkOverviewSerializer(serializers.Serializer):
    """A cooperative's farms, worst first."""

    organisation_name = serializers.CharField()
    period = serializers.CharField()
    label = serializers.CharField()
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    days = serializers.IntegerField()

    farm_count = serializers.IntegerField()
    farms_with_birds = serializers.IntegerField()
    farms_logging = serializers.IntegerField()
    logging_rate_pct = serializers.DecimalField(max_digits=5, decimal_places=1)

    birds_alive = serializers.IntegerField()
    deaths = serializers.IntegerField()
    deaths_before = serializers.IntegerField()
    feed_kg = serializers.DecimalField(max_digits=12, decimal_places=1)
    feed_bags = serializers.DecimalField(max_digits=10, decimal_places=1)

    rows = NetworkFarmRowSerializer(many=True)
    needs_attention = NetworkFarmRowSerializer(many=True)
    headline = serializers.CharField()


class OrganisationSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    kind = serializers.CharField(source="get_kind_display")
    location = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    farm_count = serializers.SerializerMethodField()

    def get_location(self, obj) -> str:
        return ", ".join(part for part in [obj.lga, obj.state] if part)

    def get_role(self, obj) -> str:
        return self.context["roles"].get(obj.id, "")

    def get_farm_count(self, obj) -> int:
        return obj.farms.count()
