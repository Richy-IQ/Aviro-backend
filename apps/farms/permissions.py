"""
Farm-scoped permissions.

Every domain object hangs off a farm, so authorisation is one question asked
consistently: does this user have a membership of that farm, and does the role
allow what they are attempting?
"""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.request import Request

from .models import Farm, Membership, Organisation, OrganisationMembership


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


def organisation_membership_for(user, organisation: Organisation) -> OrganisationMembership | None:
    return OrganisationMembership.objects.filter(user=user, organisation=organisation).first()


class IsOrganisationMember(permissions.BasePermission):
    """
    Read-only access to a cooperative's view of its farms.

    Every method is refused except the safe ones, at the permission layer rather
    than by convention. A cooperative can see how its members are doing; it can
    never write in their books. Views using this must expose the organisation
    through `get_organisation()`.
    """

    message = "You do not have access to this organisation."

    def has_permission(self, request: Request, view) -> bool:
        if request.method not in permissions.SAFE_METHODS:
            return False
        membership = organisation_membership_for(request.user, view.get_organisation())
        if membership is None:
            return False
        request.organisation_membership = membership
        return True
