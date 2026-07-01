import html
import logging
import smtplib
from email.message import EmailMessage
from typing import Iterable

import config


def _email_configured() -> bool:
    required = [
        config.JOB_ALERT_EMAIL_TO,
        config.JOB_ALERT_EMAIL_FROM,
        config.SMTP_HOST,
        config.SMTP_USERNAME,
        config.SMTP_PASSWORD,
    ]
    return all(str(value or "").strip() for value in required)


def _job_url(job: dict) -> str:
    return str(job.get("apply_url") or job.get("job_url") or "").strip()


def _plain_job_line(job: dict, index: int) -> str:
    url = _job_url(job)
    parts = [
        f"{index}. {job.get('job_title') or 'Untitled role'}",
        f"Company: {job.get('company') or 'Unknown'}",
        f"Location: {job.get('location') or 'Unknown'}",
        f"Provider: {job.get('provider') or 'unknown'}",
    ]
    if job.get("posted_at"):
        parts.append(f"Posted: {job.get('posted_at')}")
    if url:
        parts.append(f"URL: {url}")
    return "\n".join(parts)


def _html_job_item(job: dict, index: int) -> str:
    url = _job_url(job)
    title = html.escape(str(job.get("job_title") or "Untitled role"))
    company = html.escape(str(job.get("company") or "Unknown"))
    location = html.escape(str(job.get("location") or "Unknown"))
    provider = html.escape(str(job.get("provider") or "unknown"))
    posted = html.escape(str(job.get("posted_at") or ""))
    title_html = f'<a href="{html.escape(url)}">{title}</a>' if url else title
    posted_html = f"<br><strong>Posted:</strong> {posted}" if posted else ""
    return (
        f"<li style=\"margin-bottom:14px\">"
        f"<strong>{index}. {title_html}</strong><br>"
        f"<strong>Company:</strong> {company}<br>"
        f"<strong>Location:</strong> {location}<br>"
        f"<strong>Provider:</strong> {provider}"
        f"{posted_html}"
        f"</li>"
    )


def send_new_jobs_email(jobs: Iterable[dict], source_label: str = "JobTrack") -> bool:
    jobs = list(jobs)
    if not jobs:
        return False
    if not _email_configured():
        logging.info(
            "Job alert email skipped. Configure JOB_ALERT_EMAIL_TO, SMTP_HOST, SMTP_USERNAME, and SMTP_PASSWORD."
        )
        return False

    max_items = 40
    shown_jobs = jobs[:max_items]
    hidden_count = max(len(jobs) - len(shown_jobs), 0)
    subject = f"JobTrack alert: {len(jobs)} new matching job(s)"

    plain_lines = [
        f"{len(jobs)} new matching job(s) were scraped from {source_label}.",
        "",
        *[_plain_job_line(job, index) + "\n" for index, job in enumerate(shown_jobs, start=1)],
    ]
    if hidden_count:
        plain_lines.append(f"{hidden_count} more job(s) were saved in JobTrack.")

    html_items = "\n".join(_html_job_item(job, index) for index, job in enumerate(shown_jobs, start=1))
    more_html = f"<p>{hidden_count} more job(s) were saved in JobTrack.</p>" if hidden_count else ""

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = str(config.JOB_ALERT_EMAIL_FROM)
    message["To"] = str(config.JOB_ALERT_EMAIL_TO)
    message.set_content("\n".join(plain_lines))
    message.add_alternative(
        f"""
        <html>
          <body>
            <p><strong>{len(jobs)} new matching job(s)</strong> were scraped from {html.escape(source_label)}.</p>
            <ol>{html_items}</ol>
            {more_html}
          </body>
        </html>
        """,
        subtype="html",
    )

    try:
        with smtplib.SMTP(str(config.SMTP_HOST), int(config.SMTP_PORT), timeout=30) as smtp:
            smtp.starttls()
            smtp.login(str(config.SMTP_USERNAME), str(config.SMTP_PASSWORD))
            smtp.send_message(message)
        logging.info("Sent job alert email with %s new job(s).", len(jobs))
        return True
    except Exception as exc:
        logging.warning("Could not send job alert email: %s", exc)
        return False
