"""
Farm-scoped permissions.

Every domain object hangs off a farm, so authorisation is one question asked
consistently: does this user have a membership of that farm, and does the role
allow what they are attempting?
"""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.request import Request

from .models import Farm, Membership


def membership_for(user, farm: Farm) -> Membership | None:
    return Membership.objects.filter(user=user, farm=farm).first()


class IsFarmMember(permissions.BasePermission):
    """
    Read access for any member; write access for anyone who is not a viewer.

    Views using this must expose the farm through `get_farm()`.
    """

    message = "You do not have access to this farm."

    def has_permission(self, request: Request, view) -> bool:
        farm = view.get_farm()
        membership = membership_for(request.user, farm)
        if membership is None:
            return False
        # Cache it: views routinely need the role after the check passes.
        request.membership = membership
        if request.method in permissions.SAFE_METHODS:
            return True
        return membership.can_write


class CanManageTeam(IsFarmMember):
    message = "Only the owner or a farm manager can change the team."

    def has_permission(self, request: Request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.membership.can_manage_team
