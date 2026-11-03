from django.test import TestCase
from django.urls import reverse
from django.http import HttpResponse
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied

from .models import User, Role
from .decorators import role_required


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='doc1', password='pw12345', staff_id='WCH-1001', role=Role.DOCTOR,
        )

    def test_dashboard_redirects_anonymous_to_login(self):
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_valid_login_reaches_dashboard(self):
        logged_in = self.client.login(username='doc1', password='pw12345')
        self.assertTrue(logged_in)
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_invalid_login_shows_form_error(self):
        response = self.client.post(reverse('accounts:login'), {'username': 'doc1', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)  # re-renders form, no redirect
        self.assertContains(response, "correct")  # Django's default auth error mentions "correct username/password"

    def test_logout_rejects_get(self):
        """Regression guard: Django 5+'s LogoutView is POST-only; a GET link
        here previously produced a 405 for every user trying to sign out."""
        self.client.login(username='doc1', password='pw12345')
        response = self.client.get(reverse('accounts:logout'))
        self.assertEqual(response.status_code, 405)

    def test_logout_ends_session(self):
        self.client.login(username='doc1', password='pw12345')
        self.client.post(reverse('accounts:logout'))
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 302)


class RoleRequiredDecoratorTests(TestCase):
    """Unit-tests the @role_required decorator in isolation, independent of any view."""

    def setUp(self):
        self.factory = RequestFactory()
        self.doctor = User.objects.create_user(username='doc', password='x', staff_id='WCH-2001', role=Role.DOCTOR)
        self.billing = User.objects.create_user(username='bill', password='x', staff_id='WCH-2002', role=Role.BILLING)
        self.admin = User.objects.create_superuser(username='root', password='x', staff_id='WCH-2003', role=Role.ADMIN)

        @role_required(Role.DOCTOR, Role.NURSE)
        def clinical_only(request):
            return HttpResponse('ok')

        self.view = clinical_only

    def test_allowed_role_passes(self):
        request = self.factory.get('/')
        request.user = self.doctor
        response = self.view(request)
        self.assertEqual(response.status_code, 200)

    def test_disallowed_role_raises_permission_denied(self):
        request = self.factory.get('/')
        request.user = self.billing
        with self.assertRaises(PermissionDenied):
            self.view(request)

    def test_superuser_bypasses_role_check(self):
        request = self.factory.get('/')
        request.user = self.admin
        response = self.view(request)
        self.assertEqual(response.status_code, 200)

    def test_anonymous_user_raises_permission_denied(self):
        request = self.factory.get('/')
        request.user = AnonymousUser()
        with self.assertRaises(PermissionDenied):
            self.view(request)
