from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Let members log in with either their username or their email address."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        username = username or kwargs.get(User.USERNAME_FIELD)
        if not username or password is None:
            return None
        lookup = {'email__iexact': username} if '@' in username else {'username__iexact': username}
        candidates = list(User.objects.filter(**lookup)[:2])
        if len(candidates) != 1:
            # Unknown or ambiguous identifier: burn the same time as a real check.
            User().set_password(password)
            return None
        user = candidates[0]
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
