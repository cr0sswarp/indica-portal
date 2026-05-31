"""
Gmail Whitelist Archiver
Keeps emails addressed TO makino@indicalab.com in inbox.
Archives everything else (unread, without marking as read).
"""

import imaplib
import email
import os
import sys

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
KEEP_ADDRESS = "makino@indicalab.com"


def should_keep(msg) -> bool:
    headers_to_check = ["To", "Cc", "Delivered-To", "X-Original-To"]
    for header in headers_to_check:
        value = msg.get(header, "")
        if KEEP_ADDRESS.lower() in value.lower():
            return True
    return False


def archive_non_whitelisted():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    mail.select("INBOX")

    _, data = mail.search(None, "ALL")
    uids = data[0].split()

    if not uids:
        print("No messages in inbox.")
        mail.logout()
        return

    archived = 0
    for uid in uids:
        _, msg_data = mail.fetch(uid, "(RFC822.HEADER)")
        msg = email.message_from_bytes(msg_data[0][1])

        if not should_keep(msg):
            # Copy to All Mail (archive), then delete from inbox
            mail.copy(uid, "[Gmail]/All Mail")
            mail.store(uid, "+FLAGS", "\\Deleted")
            archived += 1
            print(f"Archived: {msg.get('Subject', '(no subject)')} | From: {msg.get('From', '')}")

    if archived:
        mail.expunge()

    print(f"Done. Archived {archived} of {len(uids)} messages.")
    mail.logout()


if __name__ == "__main__":
    archive_non_whitelisted()
