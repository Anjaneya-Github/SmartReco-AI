"""
app/services/email_service.py
-------------------------------
Lightweight email notification service using Python's built-in smtplib.

Sends personalised recommendation digests to users.
Gracefully no-ops when SMTP is not configured — the app works without email.

Configure in .env:
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=your@gmail.com
    SMTP_PASSWORD=your_app_password   # Gmail: use App Password, not account password
    EMAIL_FROM=SmartReco AI <your@gmail.com>
    EMAIL_ENABLED=true
"""
from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmailService:
    """Send recommendation digest emails via SMTP."""

    def __init__(self) -> None:
        self._enabled = (
            settings.EMAIL_ENABLED
            and bool(settings.SMTP_HOST)
            and bool(settings.SMTP_USER)
            and bool(settings.SMTP_PASSWORD)
        )
        if not self._enabled:
            logger.debug("EmailService: SMTP not configured — email notifications disabled.")

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def send_recommendation_digest(
        self,
        to_email: str,
        user_name: str,
        summary: str,
        products: list[dict[str, Any]],
        confidence: float,
        dashboard_url: str = "http://localhost:8000/dashboard",
    ) -> bool:
        """
        Send a personalised recommendation digest email.

        Args:
            to_email:      Recipient email address.
            user_name:     Display name (or email if no name).
            summary:       LLM-generated recommendation story.
            products:      List of recommended product dicts (title, category, difficulty).
            confidence:    Confidence score [0.0, 1.0].
            dashboard_url: Link to the user's dashboard.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self._enabled:
            logger.debug("Email skipped (SMTP not configured). to=%s", to_email)
            return False

        subject = f"Your personalised AI recommendations are ready — SmartReco AI"
        html    = self._build_html(user_name, summary, products, confidence, dashboard_url)
        text    = self._build_text(user_name, summary, products, confidence, dashboard_url)

        return self._send(to_email, subject, html, text)

    def send_welcome(self, to_email: str, user_name: str) -> bool:
        """Send a welcome email after registration."""
        if not self._enabled:
            return False
        subject = "Welcome to SmartReco AI!"
        html = f"""
        <html><body style="font-family:sans-serif;background:#12121f;color:#e0e0e0;padding:24px">
          <h2 style="color:#0d6efd">Welcome to SmartReco AI, {user_name}!</h2>
          <p>Start browsing courses and we'll personalise your recommendations as you interact.</p>
          <a href="http://localhost:8000/products"
             style="background:#0d6efd;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none">
            Browse Courses
          </a>
        </body></html>"""
        text = f"Welcome to SmartReco AI, {user_name}! Browse courses at http://localhost:8000/products"
        return self._send(to_email, subject, html, text)

    # ------------------------------------------------------------------ #
    # HTML/Text builders                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_html(
        name: str,
        summary: str,
        products: list[dict],
        confidence: float,
        url: str,
    ) -> str:
        conf_pct   = int(confidence * 100)
        conf_color = "#28a745" if confidence >= 0.75 else ("#ffc107" if confidence >= 0.45 else "#6c757d")
        conf_label = "HIGH" if confidence >= 0.75 else ("MEDIUM" if confidence >= 0.45 else "LOW")

        product_rows = "".join(
            f"""<tr>
              <td style="padding:8px 12px;border-bottom:1px solid #2a2a3e">
                <strong style="color:#e0e0e0">{p.get('title','')}</strong><br/>
                <span style="color:#aaa;font-size:12px">
                  {p.get('category','') or ''} &nbsp;·&nbsp; {p.get('difficulty','') or ''}
                </span>
              </td>
            </tr>"""
            for p in products[:5]
        )

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#12121f;font-family:'Segoe UI',sans-serif;color:#e0e0e0">
  <div style="max-width:600px;margin:32px auto;background:#1e1e2e;border-radius:12px;overflow:hidden">

    <!-- Header -->
    <div style="background:#0d6efd;padding:24px 32px">
      <h1 style="margin:0;color:#fff;font-size:22px">&#x1F916; SmartReco AI</h1>
      <p style="margin:6px 0 0;color:#cce0ff;font-size:14px">Your personalised learning recommendations</p>
    </div>

    <!-- Body -->
    <div style="padding:28px 32px">
      <p style="font-size:16px">Hi <strong>{name}</strong>,</p>
      <p style="color:#aaa;line-height:1.6">{summary or 'Your personalised recommendations are ready.'}</p>

      <!-- Confidence badge -->
      <div style="margin:16px 0">
        <span style="background:{conf_color};color:#fff;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:600">
          {conf_label} {conf_pct}% confidence
        </span>
      </div>

      <!-- Course list -->
      <h3 style="color:#0d6efd;margin:20px 0 10px">&#x1F4DA; Recommended Courses</h3>
      <table style="width:100%;border-collapse:collapse;background:#12121f;border-radius:8px;overflow:hidden">
        {product_rows}
      </table>

      <!-- CTA -->
      <div style="text-align:center;margin-top:28px">
        <a href="{url}"
           style="background:#0d6efd;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:600;font-size:15px">
          View Full Dashboard &#x2192;
        </a>
      </div>
    </div>

    <!-- Footer -->
    <div style="background:#16162a;padding:16px 32px;text-align:center">
      <p style="margin:0;color:#555;font-size:12px">
        SmartReco AI &nbsp;·&nbsp; AI-powered learning recommendations
        &nbsp;·&nbsp; <a href="{url}" style="color:#555">Unsubscribe</a>
      </p>
    </div>
  </div>
</body></html>"""

    @staticmethod
    def _build_text(
        name: str,
        summary: str,
        products: list[dict],
        confidence: float,
        url: str,
    ) -> str:
        lines = [
            f"Hi {name},",
            "",
            summary or "Your personalised recommendations are ready.",
            "",
            f"Confidence: {int(confidence * 100)}%",
            "",
            "Recommended Courses:",
        ]
        for i, p in enumerate(products[:5], 1):
            lines.append(f"  {i}. {p.get('title','')} ({p.get('difficulty','')} · {p.get('category','')})")
        lines += ["", f"View your dashboard: {url}", "", "— SmartReco AI"]
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # SMTP send                                                           #
    # ------------------------------------------------------------------ #

    def _send(self, to: str, subject: str, html: str, text: str) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = settings.EMAIL_FROM or settings.SMTP_USER
            msg["To"]      = to

            msg.attach(MIMEText(text, "plain"))
            msg.attach(MIMEText(html, "html"))

            context = ssl.create_default_context()
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.ehlo()
                server.starttls(context=context)
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.SMTP_USER, to, msg.as_string())

            logger.info("Email sent. to=%s subject=%s", to, subject[:60])
            return True

        except Exception as exc:
            logger.error("Email send failed. to=%s error=%s", to, exc)
            return False
