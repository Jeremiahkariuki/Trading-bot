"""
accounts/models.py

Lightweight trader user model for the Wall Street 5 Trading Bot.
Stores registered users in SQLite — no Django auth dependency needed.
"""

import hashlib
import secrets
from django.db import models
from django.utils import timezone


class TraderAccount(models.Model):
    """
    A registered trader account.
    Password is stored as a salted SHA-256 hash (salt:hash format).
    """
    username   = models.CharField(max_length=50, unique=True)
    email      = models.EmailField(max_length=254, unique=True)
    password_hash = models.CharField(max_length=128)   # "salt$sha256hex"
    is_active  = models.BooleanField(default=True)
    is_admin   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)
    login_count = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = 'accounts'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.username} <{self.email}>"

    # ── Password helpers ──────────────────────────────────────────────────────
    @staticmethod
    def make_hash(password: str, salt: str = None) -> str:
        """Return 'salt$sha256_hex' string."""
        if salt is None:
            salt = secrets.token_hex(16)
        digest = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
        return f"{salt}${digest}"

    def set_password(self, password: str) -> None:
        self.password_hash = self.make_hash(password)

    def check_password(self, password: str) -> bool:
        try:
            salt, stored = self.password_hash.split('$', 1)
            return self.make_hash(password, salt) == self.password_hash
        except (ValueError, AttributeError):
            return False

    def record_login(self) -> None:
        self.last_login = timezone.now()
        self.login_count += 1
        self.save(update_fields=['last_login', 'login_count'])
