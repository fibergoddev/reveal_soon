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
    CollectionError,  # Changed from ConnectionError
    UnknownError,
    ClientError,
    RateLimitError,
    ProxyAddressIsBlocked,
    TwoFactorRequired,
    UserNotFound  # Added for user search
)
from pathlib import Path
import config

# --- Configuration ---
USERNAME = os.environ.get("INSTA_USERNAME", config.username)
PASSWORD = os.environ.get("INSTA_PASSWORD", config.password)
SETTINGS_FILE = "instagrapi_session.json"
PROXY = None
REFRESH_INTERVAL = 5  

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

    session_data = None
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                session_data = json.load(f)
            logger.info(f"Loaded session settings from {SETTINGS_FILE}")
        except json.JSONDecodeError:
            logger.warning(f"Could not decode JSON from {SETTINGS_FILE}. Will attempt fresh login.")
        except Exception as e:
            logger.error(f"Error loading session file {SETTINGS_FILE}: {e}. Will attempt fresh login.")

    login_via_session_block_success = False
    login_via_pw_relogin_success = False

    if session_data:
        try:
            cl.set_settings(session_data)
            logger.info("Attempting login using loaded session or username/password if session is stale...")
            cl.login(USERNAME, PASSWORD)
            logger.info("Login attempt completed. Validating by fetching timeline feed...")
            cl.get_timeline_feed()
            login_via_session_block_success = True
            logger.info("Successfully logged in (session was valid or re-authentication successful within session block).")
            current_settings = cl.get_settings()
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(current_settings, f)
            logger.info(f"Session settings saved/updated to {SETTINGS_FILE}")
        except LoginRequired:
            logger.warning("LoginRequired: Session invalid or initial auth failed. Attempting explicit re-login.")
            old_settings = cl.get_settings()
            cl.set_settings({})
            if "uuids" in old_settings and old_settings.get("uuids"):
                try:
                    cl.set_uuids(old_settings["uuids"])
                    logger.info("Preserved UUIDs for re-login.")
                except Exception as e:
                    logger.warning(f"Could not preserve UUIDs: {e}")
            try:
                logger.info("Attempting re-login with username and password...")
                cl.login(USERNAME, PASSWORD)
                logger.info("Successfully re-logged in via username and password.")
                with open(SETTINGS_FILE, 'w') as f:
                    json.dump(cl.get_settings(), f)
                logger.info(f"New session settings saved to {SETTINGS_FILE} after re-login.")
                login_via_pw_relogin_success = True
            except ChallengeRequired as e_challenge_relogin:
                logger.error(f"Challenge required during re-login: {e_challenge_relogin}.")
                return None
            except BadPassword as e_bp_relogin:
                logger.error(f"Incorrect password during re-login: {e_bp_relogin}.")
                return None
            except Exception as e_relogin:
                logger.error(f"Couldn't re-login user after session invalidation: {e_relogin}")
                return None
        except BadPassword:
            logger.error("Incorrect password during session-based login attempt.")
            return None
        except ChallengeRequired as e_challenge_session:
            logger.error(f"Challenge required during session-based login attempt: {e_challenge_session}.")
            return None
        except (CollectionError, UnknownError, ClientError, RateLimitError, ProxyAddressIsBlocked, TwoFactorRequired) as e_api_session:
            logger.error(f"API error during session login attempt: {e_api_session}. Will proceed to fresh login if necessary.")
        except Exception as e_session_other:
            logger.error(f"An unexpected error occurred during session login attempt: {e_session_other}. Will proceed to fresh login if necessary.")

    if not login_via_session_block_success and not login_via_pw_relogin_success:
        logger.info("No valid session or session login failed. Attempting fresh login.")
        cl = Client()
        if PROXY:
            try:
                cl.set_proxy(PROXY)
            except Exception as e_proxy_fresh:
                logger.error(f"Failed to set proxy for fresh login: {e_proxy_fresh}")
        try:
            cl.login(USERNAME, PASSWORD)
            logger.info("Successfully performed fresh login.")
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(cl.get_settings(), f)
            logger.info(f"New session settings saved to {SETTINGS_FILE}")
        except ChallengeRequired as e_challenge_fresh:
            logger.error(f"Challenge required during fresh login: {e_challenge_fresh}.")
            return None
        except BadPassword as e_bp_fresh:
            logger.error(f"Incorrect password during fresh login: {e_bp_fresh}.")
            return None
        except (CollectionError, UnknownError, ClientError, RateLimitError, ProxyAddressIsBlocked, TwoFactorRequired) as e_api_fresh:
            logger.error(f"API error during fresh login: {e_api_fresh}")
            return None
        except Exception as e_fresh_other:
            logger.error(f"Couldn't login user (fresh attempt): {e_fresh_other}")
            return None

    if not cl.user_id:
        logger.critical("All login attempts failed.")
        return None
    return cl

# --- Helper Functions ---
def apply_random_delay(min_sec=1, max_sec=3):
    delay = random.uniform(min_sec, max_sec)
    logger.debug(f"Pausing for {delay:.2f} seconds...")
    time.sleep(delay)

# --- Main Inbox Control Functions ---
def display_inbox_threads(cl: Client, limit: int = 20):
    logger.info(f"\n--- Fetching Inbox Threads (Limit: {limit}) ---")
    try:
        threads = cl.direct_threads(amount=limit)
        if not threads:
            logger.info("No threads found in inbox.")
            return None
        logger.info("Your Inbox Threads:")
        for i, thread in enumerate(threads):
            user_names = ', '.join([user.username for user in thread.users if hasattr(user, 'username')])
            last_message_text = 'N/A'
            if thread.messages:
                last_msg = thread.messages[0]
                if last_msg.item_type == "text":
                    last_message_text = last_msg.text
                else:
                    last_message_text = f"({last_msg.item_type})"
            logger.info(f"  [{i+1}] Users: {user_names} (ID: {thread.id})")
            logger.info(f"      Last Message: {last_message_text[:75]}{'...' if len(last_message_text)>75 else ''}")
        return threads
    except ClientError as e:
        logger.error(f"ClientError fetching threads: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching threads: {e}")
    return None


def display_thread_messages(cl: Client, thread_id: str, limit: int = 20):
    """
    Fetch and display the most recent messages for a given thread using the correct endpoint.
    """
    logger.info(f"""
--- Messages for Thread ID: {thread_id} (Limit: {limit}) ---""")
    try:
        # Use direct_thread to fetch messages via the /items endpoint
        thread = cl.direct_thread(thread_id)
        messages = thread.messages[-limit:]
        if not messages:
            logger.info(f"No messages found in thread {thread_id}.")
            return False
        logger.info("Messages (Older to Newer):")
        for msg in messages:
            # Determine timestamp
            ts = msg.timestamp
            if isinstance(ts, datetime):
                dt = ts
            else:
                # msg.timestamp is in microseconds
                dt = datetime.fromtimestamp(ts / 1000000)
            timestamp_str = dt.strftime('%Y-%m-%d %H:%M:%S')

            # Determine sender
            if msg.user_id == cl.user_id:
                sender = "You"
            elif hasattr(msg, 'user') and msg.user and hasattr(msg.user, 'username'):
                sender = msg.user.username
            else:
                sender = f"User ID: {msg.user_id}"

            # Determine content
            if msg.item_type == "text":
                content = msg.text
            elif msg.item_type == "media" and msg.media:
                content = f"Media (Type: {getattr(msg.media, 'media_type', 'N/A')}, URL: {getattr(msg.media, 'thumbnail_url', 'N/A')})"
            elif msg.item_type == "like":
                content = "❤️"
            else:
                content = f"Item type: {msg.item_type}"

            print(f"  [{timestamp_str} - {sender}]: {content}")
        return True
    except ClientError as e:
        logger.error(f"ClientError fetching messages for thread {thread_id}: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching messages: {e}")
    return False

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

def continuous_chat(cl: Client, thread_id: str):
    """
    Continuously refresh messages and allow the user to reply in a chat-like flow.
    """
    print(f"\n--- Entering continuous chat with thread: {thread_id} ---")
    last_ts = None
    try:
        thread = cl.direct_thread(thread_id)
        user_map = {u.pk: u.username for u in thread.users}
        while True:
            thread = cl.direct_thread(thread_id)
            messages = thread.messages[-20:]
            last_ts = print_new_messages(cl, messages, user_map, last_ts)
            user_input = input("\nType your reply (or 'exit' to leave chat): ")
            if user_input.lower() == 'exit':
                print("Exiting chat mode.")
                break
            if user_input.strip():
                cl.direct_send(user_input, thread_ids=[thread_id])
            time.sleep(REFRESH_INTERVAL)
    except KeyboardInterrupt:
        print("Chat interrupted.")
    except Exception as e:
        logger.error(f"Error in continuous chat mode: {e}")

def send_text_message_interactive(cl: Client, user_ids: list[int] = None, thread_ids: list[str] = None):
    """Prompts user for text and sends a message."""
    if not (user_ids or thread_ids):
        logger.error("Error: No recipient specified for sending message.")
        return
    
    try:
        text_to_send = input("Type your message: ")
        if not text_to_send.strip():
            logger.info("Message is empty. Skipping send.")
            return

        _user_ids = [int(uid) for uid in user_ids] if user_ids else []
        _thread_ids = [str(tid) for tid in thread_ids] if thread_ids else []

        sent_message = cl.direct_send(text_to_send, user_ids=_user_ids, thread_ids=_thread_ids)
        if sent_message:
            logger.info(f"Message sent successfully. (Message ID: {getattr(sent_message, 'id', 'N/A')})")
        else:
            logger.warning("Message send operation returned no message object or a falsy value.")
    except ClientError as e:
        logger.error(f"ClientError sending text message: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while sending text message: {e}")

def approve_all_pending_requests_interactive(cl: Client):
    """Approves all pending requests in the inbox with confirmation."""
    logger.info("\n--- Approving All Pending Inbox Requests ---")
    confirm = input("Are you sure you want to approve ALL pending message requests? (yes/no): ").lower()
    if confirm == 'yes':
        try:
            result = cl.direct_pending_approve_all()
            logger.info(f"All pending inbox requests approval process initiated. Result: {result}")
        except ClientError as e:
            logger.error(f"ClientError approving pending requests: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while approving pending requests: {e}")
    else:
        logger.info("Approval of pending requests cancelled.")

# --- Main Interactive Script ---
if __name__ == "__main__":
    if USERNAME == "your_instagram_username" or PASSWORD == "your_instagram_password":
        logger.warning("Default username/password detected. Please set your credentials.")
        # exit()

    client = login_user()

    if client:
        logger.info(f"\n--- Client successfully initialized. Logged in as User ID: {client.user_id} ---")
        
        while True:
            print("\nWhat would you like to do?")
            print("  1. View Inbox Threads")
            print("  2. Search User & Chat")
            print("  3. Approve All Pending Requests")
            print("  4. Exit")
            choice = input("Enter your choice (1-4): ")

            apply_random_delay()

            if choice == '1':
                threads = display_inbox_threads(client)
                if threads:
                    try:
                        thread_choice = input("Select a thread number to view messages (or type 'b' to go back): ")
                        if thread_choice.lower() == 'b':
                            continue
                        thread_index = int(thread_choice) - 1
                        if 0 <= thread_index < len(threads):
                            selected_thread_id = threads[thread_index].id
                            continuous_chat(client, selected_thread_id)
                        else:
                            logger.warning("Invalid thread number.")
                    except ValueError:
                        logger.warning("Invalid input. Please enter a number.")
                    except Exception as e:
                        logger.error(f"Error processing thread selection: {e}")
                        
            elif choice == '2':
                search_username = input("Enter username to search: ").strip()
                if not search_username:
                    logger.warning("Username cannot be empty.")
                    continue
                
                try: # Outer try for user search and subsequent logic
                    logger.info(f"Searching for user: {search_username}...")
                    user_info = client.user_info_by_username(search_username)
                    target_user_pk = user_info.pk
                    logger.info(f"User '{search_username}' found (ID: {target_user_pk}).")
                    
                    # Try to find an existing thread with this user
                    logger.info(f"Checking for existing thread with {search_username}...")
                    apply_random_delay()
                    existing_thread = None
                    try: # Inner try for thread checking logic
                        threads_check = client.direct_threads(amount=50) # Check more threads
                        for t in threads_check:
                            if len(t.users) == 2: # Assuming 1-on-1 chat
                                user_pks_in_thread = [u.pk for u in t.users]
                                if target_user_pk in user_pks_in_thread and client.user_id in user_pks_in_thread:
                                    existing_thread = t
                                    break
                        
                        if existing_thread:
                            logger.info(f"Found existing thread with {search_username} (ID: {existing_thread.id}).")
                            if display_thread_messages(client, existing_thread.id):
                                 if input(f"Reply to {search_username} in this thread? (yes/no): ").lower() == 'yes':
                                    send_text_message_interactive(client, thread_ids=[existing_thread.id])
                            elif input(f"No messages shown, or want to start fresh. Send a new message to {search_username}? (yes/no): ").lower() == 'yes':
                                send_text_message_interactive(client, user_ids=[target_user_pk])

                        else:
                            logger.info(f"No recent existing thread found with {search_username} in checked threads.")
                            if input(f"Send a new message to {search_username}? (yes/no): ").lower() == 'yes':
                                send_text_message_interactive(client, user_ids=[target_user_pk])
                    
                    except Exception as e_thread_check: # Exception handling for inner try block
                        logger.error(f"Error while checking/handling existing thread with {search_username}: {e_thread_check}")
                        # Optionally, offer to send a new message even if thread check failed
                        if input(f"Could not fully process existing threads. Send a new message to {search_username} anyway? (yes/no): ").lower() == 'yes':
                            send_text_message_interactive(client, user_ids=[target_user_pk])
                                
                except UserNotFound:
                    logger.error(f"User '{search_username}' not found.")
                except ClientError as e:
                    logger.error(f"ClientError during user search or chat initiation: {e}")
                except Exception as e: # General exception for the outer try
                    logger.error(f"An unexpected error occurred in search user & chat: {e}")

            elif choice == '3':
                approve_all_pending_requests_interactive(client) # Corrected variable name from aclient to client

            elif choice == '4':
                logger.info("Exiting script. Goodbye!")
                break
            
            else:
                logger.warning("Invalid choice. Please try again.")
        
        # Cleanly close session if needed, though instagrapi usually handles this
        # client.logout() # Optional, if you want to explicitly logout

    else:
        logger.critical("\nCould not initialize Instagram client. Exiting.")