"""Farm and team endpoints."""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.common.exceptions import DomainError

from .models import Farm, Membership, Pen
from .permissions import CanManageTeam, IsFarmMember
from .serializers import FarmSerializer, InviteSerializer, MembershipSerializer, PenSerializer


class FarmListView(APIView):
    """
    GET  /api/v1/farms/ — farms this user belongs to.
    POST /api/v1/farms/ — create one; the creator becomes its owner.
    """

    def get(self, request: Request) -> Response:
        memberships = (
            Membership.objects.filter(user=request.user)
            .select_related("farm")
            .prefetch_related("farm__pens")
        )
        farms = [m.farm for m in memberships]
        roles = {m.farm_id: m.role for m in memberships}
        return Response(
            FarmSerializer(farms, many=True, context={"roles_by_farm": roles}).data
        )

    @transaction.atomic
    def post(self, request: Request) -> Response:
        serializer = FarmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        farm = serializer.save()
        Membership.objects.create(user=request.user, farm=farm, role=Membership.Role.OWNER)
        return Response(
            FarmSerializer(farm, context={"roles_by_farm": {farm.id: Membership.Role.OWNER}}).data,
            status=status.HTTP_201_CREATED,
        )


class FarmDetailView(APIView):
    """GET and PATCH one farm."""

    permission_classes = [IsFarmMember]

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def get(self, request: Request, farm_id) -> Response:
        farm = self.get_farm()
        return Response(
            FarmSerializer(farm, context={"roles_by_farm": {farm.id: request.membership.role}}).data
        )

    def patch(self, request: Request, farm_id) -> Response:
        farm = self.get_farm()
        serializer = FarmSerializer(farm, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PenListView(APIView):
    permission_classes = [IsFarmMember]

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def get(self, request: Request, farm_id) -> Response:
        return Response(PenSerializer(self.get_farm().pens.all(), many=True).data)

    def post(self, request: Request, farm_id) -> Response:
        serializer = PenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(farm=self.get_farm())
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TeamView(APIView):
    """
    GET  /api/v1/farms/<farm_id>/team/ — who can act on this farm.
    POST /api/v1/farms/<farm_id>/team/ — invite someone by phone number.

    The invited person may not have an account yet. One is created, dormant,
    and becomes theirs when they verify that number — which is why the account
    is a person rather than a farm.
    """

    permission_classes = [CanManageTeam]

    def get_farm(self) -> Farm:
        return get_object_or_404(Farm, pk=self.kwargs["farm_id"])

    def get(self, request: Request, farm_id) -> Response:
        team = (
            Membership.objects.filter(farm=self.get_farm())
            .select_related("user")
            .prefetch_related("pens")
        )
        return Response(MembershipSerializer(team, many=True).data)

    @transaction.atomic
    def post(self, request: Request, farm_id) -> Response:
        farm = self.get_farm()
        serializer = InviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]

        if serializer.validated_data["role"] == Membership.Role.OWNER:
            raise DomainError("A farm has one owner. Transfer ownership instead of inviting one.")

        user, _ = User.objects.get_or_create(phone=phone)
        if Membership.objects.filter(user=user, farm=farm).exists():
            raise DomainError("That person is already on this farm.")

        membership = Membership.objects.create(
            user=user,
            farm=farm,
            role=serializer.validated_data["role"],
            invited_by=request.user,
        )
        pen_ids = serializer.validated_data.get("pen_ids") or []
        if pen_ids:
            membership.pens.set(Pen.objects.filter(farm=farm, id__in=pen_ids))

        return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)
