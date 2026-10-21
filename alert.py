"""Email a short alert when the scheduled run fails, with a link to the failed run's log."""
import os
import smtplib
from email.mime.text import MIMEText

run = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
       f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}")
sender = os.environ["GMAIL_ADDRESS"]
msg = MIMEText("This morning's Daily Letter run failed, so the letter may not have arrived.\n\n"
               f"The log shows what went wrong: {run}\n")
msg["Subject"] = "Daily Letter: this morning's run failed"
msg["From"] = sender
msg["To"] = os.environ.get("TO_ADDRESS", sender)
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(sender, os.environ["GMAIL_APP_PASSWORD"])
    server.send_message(msg)
print("Failure alert sent")
