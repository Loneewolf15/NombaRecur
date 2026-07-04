import logging
from app.config import settings

logger = logging.getLogger(__name__)


def _send(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """Low-level send via Sendbyte API. Returns True on success, False on failure."""
    import httpx
    url = "https://api.sendbyte.africa/v1/emails"
    headers = {
        "Authorization": f"Bearer {settings.sendbyte_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": to_email,
        "from": settings.email_from,
        "subject": subject,
        "html": html_body,
        "text": text_body
    }
    
    try:
        res = httpx.post(url, headers=headers, json=payload, timeout=10.0)
        res.raise_for_status()
        logger.info(f"Sendbyte Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email via Sendbyte to {to_email}: {e}")
        return False


def send_dunning_email(customer_email: str, customer_name: str, checkout_link: str, amount_naira: str, plan_name: str) -> bool:
    """
    Sent when Rail 1 (card charge) fails and we fall back to a manual checkout link.
    """
    subject = f"Action required: Your {plan_name} subscription payment failed"
    display_name = customer_name or customer_email

    html_body = f"""
    <html><body style="font-family: sans-serif; color: #333;">
      <h2 style="color: #c0392b;">Payment Unsuccessful</h2>
      <p>Hi {display_name},</p>
      <p>We were unable to automatically renew your <strong>{plan_name}</strong> subscription
         for <strong>₦{amount_naira}</strong>.</p>
      <p>Please complete your payment to avoid service interruption:</p>
      <p style="text-align:center; margin: 24px 0;">
        <a href="{checkout_link}"
           style="background:#2ecc71;color:#fff;padding:12px 28px;border-radius:6px;
                  text-decoration:none;font-weight:bold;font-size:16px;">
          Pay Now →
        </a>
      </p>
      <p style="color:#888;font-size:12px;">
        This link is unique to your account. Do not share it.
      </p>
    </body></html>
    """

    text_body = (
        f"Hi {display_name},\n\n"
        f"We could not charge your card for the {plan_name} subscription (₦{amount_naira}).\n\n"
        f"Please pay here to keep your subscription active:\n{checkout_link}\n\n"
        f"— NombaRecur Billing"
    )

    return _send(customer_email, subject, html_body, text_body)


def send_payment_failed_email(customer_email: str, customer_name: str, amount_naira: str, plan_name: str) -> bool:
    """
    Sent when a payment attempt is definitively declined (not a soft dunning —
    this fires when the subscription is canceled due to max retries being exhausted,
    or when Nomba returns an explicit decline with no further fallback available).
    """
    subject = f"Your {plan_name} subscription has been canceled"
    display_name = customer_name or customer_email

    html_body = f"""
    <html><body style="font-family: sans-serif; color: #333;">
      <h2 style="color: #c0392b;">Subscription Canceled</h2>
      <p>Hi {display_name},</p>
      <p>Unfortunately we were unable to collect payment of <strong>₦{amount_naira}</strong>
         for your <strong>{plan_name}</strong> subscription after multiple attempts,
         so the subscription has been canceled.</p>
      <p>If you'd like to re-subscribe, please contact us or sign up again through the platform.</p>
      <p style="color:#888;font-size:12px;">We're sorry for the inconvenience.</p>
    </body></html>
    """

    text_body = (
        f"Hi {display_name},\n\n"
        f"We were unable to collect ₦{amount_naira} for your {plan_name} subscription "
        f"after multiple attempts, so it has been canceled.\n\n"
        f"Please re-subscribe if you'd like to continue.\n\n"
        f"— NombaRecur Billing"
    )

    return _send(customer_email, subject, html_body, text_body)


def send_payment_success_email(customer_email: str, customer_name: str, amount_naira: str, plan_name: str, next_billing_date: str) -> bool:
    """
    Sent when a payment (any rail) is confirmed via webhook.
    """
    subject = f"Payment confirmed — {plan_name} subscription renewed"
    display_name = customer_name or customer_email

    html_body = f"""
    <html><body style="font-family: sans-serif; color: #333;">
      <h2 style="color: #27ae60;">Payment Confirmed ✓</h2>
      <p>Hi {display_name},</p>
      <p>Your <strong>{plan_name}</strong> subscription has been successfully renewed
         for <strong>₦{amount_naira}</strong>.</p>
      <table style="border-collapse:collapse;width:100%;max-width:400px;margin:16px 0;">
        <tr>
          <td style="padding:8px;border:1px solid #ddd;font-weight:bold;">Plan</td>
          <td style="padding:8px;border:1px solid #ddd;">{plan_name}</td>
        </tr>
        <tr>
          <td style="padding:8px;border:1px solid #ddd;font-weight:bold;">Amount Paid</td>
          <td style="padding:8px;border:1px solid #ddd;">₦{amount_naira}</td>
        </tr>
        <tr>
          <td style="padding:8px;border:1px solid #ddd;font-weight:bold;">Next Renewal</td>
          <td style="padding:8px;border:1px solid #ddd;">{next_billing_date}</td>
        </tr>
      </table>
      <p style="color:#888;font-size:12px;">Thank you for your subscription.</p>
    </body></html>
    """

    text_body = (
        f"Hi {display_name},\n\n"
        f"Your {plan_name} subscription was renewed for ₦{amount_naira}.\n"
        f"Next renewal date: {next_billing_date}\n\n"
        f"— NombaRecur Billing"
    )

    return _send(customer_email, subject, html_body, text_body)
