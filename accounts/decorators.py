from functools import wraps

from django.core.exceptions import PermissionDenied

from .permissions import has_role


def role_required(*roles):
    """Restrict a view to the given accounts.Role values (superusers pass).
    Usage: @role_required(*BILLING_ROLES)
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if has_role(request.user, roles):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied
        return _wrapped
    return decorator
