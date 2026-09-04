from rest_framework import serializers

from .phone import InvalidPhoneNumber, to_e164


class PhoneField(serializers.CharField):
    """Accepts any way a Nigerian writes their number; stores E.164."""

    def to_internal_value(self, data) -> str:
        value = super().to_internal_value(data)
        try:
            return to_e164(value)
        except InvalidPhoneNumber as exc:
            raise serializers.ValidationError(
                "Enter a Nigerian mobile number, for example 0803 412 9087."
            ) from exc


class OtpRequestSerializer(serializers.Serializer):
    phone = PhoneField(max_length=24)


class OtpVerifySerializer(serializers.Serializer):
    phone = PhoneField(max_length=24)
    code = serializers.RegexField(r"^\d{6}$", error_messages={"invalid": "Enter the 6-digit code."})


class UserSerializer(serializers.Serializer):
    """The signed-in user, as the client needs them."""

    id = serializers.UUIDField(read_only=True)
    phone = serializers.CharField(read_only=True)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=60)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=60)
    state = serializers.CharField(required=False, allow_blank=True, max_length=60)
    lga = serializers.CharField(required=False, allow_blank=True, max_length=60)
    display_name = serializers.CharField(read_only=True)

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save(update_fields=[*validated_data.keys(), "updated_at"])
        return instance
