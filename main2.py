import os
import json
import time
import random
import logging
from datetime import datetime
from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired,
    BadPassword,
    LoginRequired,
    CollectionError,
    UnknownError,
    ClientError,
    RateLimitError,
    ProxyAddressIsBlocked,
    TwoFactorRequired,
    UserNotFound
)
import config

# --- Configuration ---
USERNAME = os.environ.get("INSTA_USERNAME", config.username)
PASSWORD = os.environ.get("INSTA_PASSWORD", config.password)
SETTINGS_FILE = "instagrapi_session.json"
PROXY = None
REFRESH_INTERVAL = 5  # seconds between auto-refresh polls

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Session & Login Function ---
def login_user():
    cl = Client()
    if PROXY:
        try:
            cl.set_proxy(PROXY)
            logger.info(f"Proxy set: {PROXY}")
        except Exception as e:
            logger.error(f"Failed to set proxy: {e}")
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                cl.set_settings(json.load(f))
        cl.login(USERNAME, PASSWORD)
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(cl.get_settings(), f)
    except Exception as e:
        logger.error(f"Login failed: {e}")
        return None
    return cl

# --- Inbox & Thread Display ---
def display_inbox_threads(cl, limit=20):
    try:
        threads = cl.direct_threads(amount=limit)
    except Exception as e:
        logger.error(f"Error fetching threads: {e}")
        return []
    for i, thread in enumerate(threads, start=1):
        names = ', '.join(u.username for u in thread.users if hasattr(u, 'username'))
        last = thread.messages[0].text if thread.messages and thread.messages[0].item_type == 'text' else '...'
        print(f"[{i}] {names} - {last[:50]}")
    return threads

# --- Message Fetch & Display ---
def fetch_thread_data(cl, thread_id, limit=20):
    """
    Returns a tuple of (sorted messages, user map) for given thread.
    """
    thread = cl.direct_thread(thread_id)
    # Build user_id->username map
    user_map = {u.pk: u.username for u in thread.users}
    # Get last 'limit' messages in chronological order
    messages = thread.messages[-limit:]
    return messages, user_map

def print_new_messages(cl, messages, user_map, last_ts=None):
    new_last = last_ts
    for msg in messages:
        ts = msg.timestamp if isinstance(msg.timestamp, datetime) else datetime.fromtimestamp(msg.timestamp / 1e6)
        if last_ts and ts <= last_ts:
            continue
        sender = "You" if msg.user_id == cl.user_id else user_map.get(msg.user_id, f"User {msg.user_id}")
        content = msg.text if msg.item_type == 'text' else f"[{msg.item_type}]"
        print(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} - {sender}: {content}")
        new_last = ts if not new_last or ts > new_last else new_last
    return new_last

# --- Auto-Refresh Loop ---
def auto_refresh_thread(cl, thread_id):
    print(f"Entering auto-refresh mode for thread {thread_id}. Polling every {REFRESH_INTERVAL}s. Press Ctrl+C to exit.")
    last_ts = None
    try:
        while True:
            messages, user_map = fetch_thread_data(cl, thread_id)
            last_ts = print_new_messages(cl, messages, user_map, last_ts)
            time.sleep(REFRESH_INTERVAL)
    except KeyboardInterrupt:
        print("Stopped auto-refresh.")

# --- Main CLI ---
def main():
    cl = login_user()
    if not cl:
        return
    while True:
        print("\n1. View Inbox Threads\n2. Open Thread with Auto-Refresh\n3. Exit")
        choice = input("Choose: ")
        if choice == '1':
            display_inbox_threads(cl)
        elif choice == '2':
            threads = display_inbox_threads(cl)
            num = input("Enter thread number: ")
            if num.isdigit() and 1 <= int(num) <= len(threads):
                tid = threads[int(num) - 1].id
                auto_refresh_thread(cl, tid)
        elif choice == '3':
            break
        else:
            print("Invalid choice.")

if __name__ == '__main__':
    main()
