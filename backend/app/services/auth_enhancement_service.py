import secrets
import pyotp
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import aiosmtplib

logger = logging.getLogger(__name__)


class AuthEnhancementService:
    """Enhanced auth with email verification, password reset, 2FA"""

    def __init__(
        self,
        smtp_host: str = None,
        smtp_port: int = 587,
        smtp_user: str = None,
        smtp_password: str = None,
        from_email: str = None,
        base_url: str = "https://mt-oc.aitradepulse.com",
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_email = from_email
        self.base_url = base_url

    def generate_verification_token(self) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        expires = datetime.utcnow() + timedelta(hours=24)
        return token, expires

    def generate_reset_token(self) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        expires = datetime.utcnow() + timedelta(hours=1)
        return token, expires

    def generate_2fa_secret(self) -> str:
        return pyotp.random_base32()

    def get_2fa_uri(self, secret: str, email: str) -> str:
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=email, issuer_name="MT5 Router")

    def verify_2fa_token(self, secret: str, token: str) -> bool:
        totp = pyotp.TOTP(secret)
        return totp.verify(token, valid_window=1)

    async def send_verification_email(self, to_email: str, token: str) -> bool:
        verification_url = f"{self.base_url}/verify-email?token={token}"

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background: #0a0d14; color: #fff; padding: 40px;">
            <div style="max-width: 500px; margin: 0 auto; background: #1a1a2e; padding: 30px; border-radius: 12px;">
                <h1 style="color: #6366f1; margin-bottom: 20px;">MT5 Router</h1>
                <h2>Verify Your Email</h2>
                <p>Please click the button below to verify your email address:</p>
                <a href="{verification_url}"
                   style="display: inline-block; background: #6366f1; color: white;
                          padding: 12px 24px; text-decoration: none; border-radius: 8px;
                          margin: 20px 0;">
                    Verify Email
                </a>
                <p style="color: #888; font-size: 12px;">This link expires in 24 hours.</p>
                <p style="color: #888; font-size: 12px;">If you didn't create an account, ignore this email.</p>
            </div>
        </body>
        </html>
        """

        return await self._send_email(
            to_email, "Verify your MT5 Router account", html_content
        )

    async def send_password_reset_email(self, to_email: str, token: str) -> bool:
        reset_url = f"{self.base_url}/reset-password?token={token}"

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background: #0a0d14; color: #fff; padding: 40px;">
            <div style="max-width: 500px; margin: 0 auto; background: #1a1a2e; padding: 30px; border-radius: 12px;">
                <h1 style="color: #6366f1; margin-bottom: 20px;">MT5 Router</h1>
                <h2>Reset Your Password</h2>
                <p>Click the button below to reset your password:</p>
                <a href="{reset_url}"
                   style="display: inline-block; background: #6366f1; color: white;
                          padding: 12px 24px; text-decoration: none; border-radius: 8px;
                          margin: 20px 0;">
                    Reset Password
                </a>
                <p style="color: #888; font-size: 12px;">This link expires in 1 hour.</p>
                <p style="color: #888; font-size: 12px;">If you didn't request a password reset, ignore this email.</p>
            </div>
        </body>
        </html>
        """

        return await self._send_email(
            to_email, "Reset your MT5 Router password", html_content
        )

    async def send_2fa_enabled_email(self, to_email: str) -> bool:
        html_content = """
        <html>
        <body style="font-family: Arial, sans-serif; background: #0a0d14; color: #fff; padding: 40px;">
            <div style="max-width: 500px; margin: 0 auto; background: #1a1a2e; padding: 30px; border-radius: 12px;">
                <h1 style="color: #6366f1; margin-bottom: 20px;">MT5 Router</h1>
                <h2>2FA Enabled</h2>
                <p>Two-factor authentication has been enabled on your account.</p>
                <p style="color: #888; font-size: 12px;">If you didn't enable this, contact support immediately.</p>
            </div>
        </body>
        </html>
        """
        return await self._send_email(
            to_email, "2FA Enabled on MT5 Router", html_content
        )

    @staticmethod
    def _validate_header_value(value: str, field: str) -> str:
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError(f"Invalid email header value for {field}")
        return value

    async def _send_email(self, to_email: str, subject: str, html_content: str) -> bool:
        if not self.smtp_host or not self.from_email:
            logger.warning("Email not configured - skipping send")
            return False

        self._validate_header_value(to_email, "To")
        self._validate_header_value(subject, "Subject")
        self._validate_header_value(self.from_email, "From")

        try:
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = self.from_email
            message["To"] = to_email

            html_part = MIMEText(html_content, "html")
            message.attach(html_part)

            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                start_tls=True,
            )

            logger.info(f"Email sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False

    def check_account_lockout(
        self, failed_attempts: int, locked_until: Optional[datetime]
    ) -> Dict[str, Any]:
        if locked_until and locked_until > datetime.utcnow():
            return {
                "locked": True,
                "locked_until": locked_until.isoformat(),
                "reason": "Too many failed login attempts",
            }
        return {"locked": False}

    def calculate_lockout(self, failed_attempts: int) -> Optional[datetime]:
        if failed_attempts >= 10:
            return datetime.utcnow() + timedelta(minutes=30)
        elif failed_attempts >= 5:
            return datetime.utcnow() + timedelta(minutes=5)
        return None


auth_enhancement_service: Optional[AuthEnhancementService] = None


def init_auth_enhancement_service(
    smtp_host: str = None,
    smtp_port: int = 587,
    smtp_user: str = None,
    smtp_password: str = None,
    from_email: str = None,
    base_url: str = None,
):
    global auth_enhancement_service
    auth_enhancement_service = AuthEnhancementService(
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
        from_email=from_email,
        base_url=base_url or "https://mt-oc.aitradepulse.com",
    )
    return auth_enhancement_service
