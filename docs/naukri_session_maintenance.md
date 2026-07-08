# Naukri Session Maintenance

Naukri and Naukri Gulf sessions can expire quickly. Run this from WSL to check
the session, open a browser when login is required, save the refreshed session,
and update the matching GitHub Actions secret.

```bash
cd /home/venkat/linkedin-jobs-scrapper
source .venv/bin/activate

python maintain_browser_sessions.py
```

Keep it running and check every hour:

```bash
python maintain_browser_sessions.py --loop --interval-minutes 60
```

Auto-fill username/password from environment variables before prompting:

```bash
export NAUKRI_USERNAME="your-email"
export NAUKRI_PASSWORD="your-password"
export NAUKRI_GULF_USERNAME="your-email"
export NAUKRI_GULF_PASSWORD="your-password"

python maintain_browser_sessions.py --auto-login --loop --interval-minutes 60
```

If Naukri asks for captcha, OTP, or device verification, the browser remains
open and you still need to complete that step manually.

Check only Naukri:

```bash
python maintain_browser_sessions.py --targets naukri
```

Check only Naukri Gulf:

```bash
python maintain_browser_sessions.py --targets naukri_gulf
```

Use `--no-secret-update` if you only want to refresh the local JSON files.
