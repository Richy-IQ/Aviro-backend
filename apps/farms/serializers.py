from rest_framework import serializers

from apps.accounts.serializers import PhoneField

from .models import Farm, Membership, Pen


class PenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pen
        fields = ["id", "name"]


class FarmSerializer(serializers.ModelSerializer):
    location = serializers.CharField(read_only=True)
    pens = PenSerializer(many=True, read_only=True)
    role = serializers.SerializerMethodField()

    class Meta:
        model = Farm
        fields = ["id", "name", "state", "lga", "location", "pens", "role", "created_at"]
        read_only_fields = ["created_at"]

    def get_role(self, farm: Farm) -> str | None:
        """The requesting user's role, so the client can hide what they cannot do."""
        memberships = self.context.get("roles_by_farm", {})
        return memberships.get(farm.id)


class MembershipSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(source="user.phone", read_only=True)
    name = serializers.CharField(source="user.display_name", read_only=True)
    pens = PenSerializer(many=True, read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "phone", "name", "role", "pens", "accepted_at", "created_at"]


class InviteSerializer(serializers.Serializer):
    """Invites are addressed to a phone number; the person verifies it themselves."""

    phone = PhoneField(max_length=24)
    role = serializers.ChoiceField(choices=Membership.Role.choices)
    pen_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
