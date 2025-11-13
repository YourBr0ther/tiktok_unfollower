#!/usr/bin/env python3
"""
TikTok Follower Cleanup Script
Automatically unfollows banned or deleted accounts from your TikTok followers list
with rate limiting to avoid hitting TikTok's limits.
"""

import os
import json
import time
import logging
import csv
import random
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Load environment variables
load_dotenv()

# Setup logging first (before any configuration that might log warnings)
def setup_logging():
    """Configure logging to both file and console"""
    logger = logging.getLogger('TikTokUnfollower')
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers if function is called multiple times
    if logger.handlers:
        return logger

    # File handler with rotation (max 5MB, keep 3 backups)
    file_handler = RotatingFileHandler(
        'tiktok_unfollower.log',
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)

    # Console handler (simpler format)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

# Initialize logger
logger = setup_logging()

# Configuration with validation
TIKTOK_USERNAME = os.getenv('TIKTOK_USERNAME')
TIKTOK_PASSWORD = os.getenv('TIKTOK_PASSWORD')
LOGIN_METHOD = os.getenv('LOGIN_METHOD', 'email').lower()  # 'email' or 'google'

# Validate login method
if LOGIN_METHOD not in ['email', 'google']:
    logger.info(f"⚠️  Invalid LOGIN_METHOD '{LOGIN_METHOD}', using 'email'")
    LOGIN_METHOD = 'email'

try:
    UNFOLLOW_DELAY = int(os.getenv('UNFOLLOW_DELAY', 10800))  # 3 hours default
    if UNFOLLOW_DELAY < 0:
        raise ValueError("UNFOLLOW_DELAY must be positive")
except ValueError as e:
    logger.info(f"⚠️  Invalid UNFOLLOW_DELAY value, using default (10800 seconds): {e}")
    UNFOLLOW_DELAY = 10800

try:
    BATCH_SIZE = int(os.getenv('BATCH_SIZE', 5))
    if BATCH_SIZE < 1:
        raise ValueError("BATCH_SIZE must be at least 1")
except ValueError as e:
    logger.info(f"⚠️  Invalid BATCH_SIZE value, using default (5): {e}")
    BATCH_SIZE = 5

try:
    ACTION_DELAY = int(os.getenv('ACTION_DELAY', 5))
    if ACTION_DELAY < 0:
        raise ValueError("ACTION_DELAY must be positive")
except ValueError as e:
    logger.info(f"⚠️  Invalid ACTION_DELAY value, using default (5 seconds): {e}")
    ACTION_DELAY = 5

# Delay between profile checks (to avoid bot detection)
try:
    PROFILE_CHECK_DELAY = int(os.getenv('PROFILE_CHECK_DELAY', 30))
    if PROFILE_CHECK_DELAY < 0:
        raise ValueError("PROFILE_CHECK_DELAY must be positive")
except ValueError as e:
    logger.info(f"⚠️  Invalid PROFILE_CHECK_DELAY value, using default (30 seconds): {e}")
    PROFILE_CHECK_DELAY = 30

HEADLESS = os.getenv('HEADLESS', 'false').lower() == 'true'

# Safety mode - when enabled, the script will scan and report but NOT actually unfollow
DRY_RUN = os.getenv('DRY_RUN', 'true').lower() == 'true'

# Limit how many followers to review (helpful for testing)
# Set to 0 or leave empty to review all followers
try:
    MAX_FOLLOWERS_TO_REVIEW = int(os.getenv('MAX_FOLLOWERS_TO_REVIEW', 0))
    if MAX_FOLLOWERS_TO_REVIEW < 0:
        raise ValueError("MAX_FOLLOWERS_TO_REVIEW must be non-negative")
except ValueError as e:
    logger.info(f"⚠️  Invalid MAX_FOLLOWERS_TO_REVIEW value, using default (0 = unlimited): {e}")
    MAX_FOLLOWERS_TO_REVIEW = 0

# Session persistence - saves login state to avoid logging in every time
SAVE_SESSION = os.getenv('SAVE_SESSION', 'true').lower() == 'true'

# File paths
STATE_FILE = 'state.json'
SESSION_FILE = 'session.json'
LOG_FILE = 'tiktok_unfollower.log'
CSV_EXPORT_FILE = 'invalid_accounts.csv'


class TikTokUnfollower:
    def __init__(self):
        self.state = self.load_state()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def load_state(self):
        """Load the state from file to track progress"""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    state = json.load(f)
                    # Validate state structure
                    if not isinstance(state, dict):
                        raise ValueError("State file is not a valid dictionary")
                    # Ensure required keys exist
                    state.setdefault('last_run', None)
                    state.setdefault('processed_accounts', [])
                    state.setdefault('unfollowed_accounts', [])
                    return state
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Corrupted state file ({e}). Starting fresh.")
                # Backup corrupted file
                backup_file = f'{STATE_FILE}.backup'
                try:
                    os.rename(STATE_FILE, backup_file)
                    logger.info(f"Old state backed up to {backup_file}")
                except Exception:
                    pass

        return {
            'last_run': None,
            'processed_accounts': [],
            'unfollowed_accounts': []
        }

    def save_state(self):
        """Save the current state to file"""
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(self.state, f, indent=2)
        except (IOError, OSError) as e:
            logger.warning(f"Could not save state to {STATE_FILE}: {e}")
            # Don't raise - allow script to continue even if state save fails

    def should_run(self):
        """Check if enough time has passed since last run"""
        if not self.state['last_run']:
            return True

        last_run = datetime.fromisoformat(self.state['last_run'])
        next_run = last_run + timedelta(seconds=UNFOLLOW_DELAY)

        if datetime.now() < next_run:
            wait_time = (next_run - datetime.now()).total_seconds()
            logger.info(f"⏰ Too soon to run again. Wait {wait_time/3600:.2f} hours")
            return False

        return True

    def export_to_csv(self, invalid_accounts):
        """Export invalid accounts to CSV file"""
        try:
            # Check if file exists to determine if we need to write headers
            file_exists = os.path.exists(CSV_EXPORT_FILE)

            with open(CSV_EXPORT_FILE, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)

                # Write header if file is new
                if not file_exists:
                    writer.writerow(['Timestamp', 'Username', 'Detection Reason'])

                # Write account data
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                for account in invalid_accounts:
                    writer.writerow([
                        timestamp,
                        account.get('username', 'Unknown'),
                        account.get('reason', 'Invalid account detected')
                    ])

            logger.info(f"📄 Exported {len(invalid_accounts)} invalid accounts to {CSV_EXPORT_FILE}")
        except Exception as e:
            logger.warning(f"Could not export to CSV: {e}")

    def load_session(self):
        """Load saved browser session if available"""
        if SAVE_SESSION and os.path.exists(SESSION_FILE):
            try:
                logger.info("📂 Loading saved session...")
                return SESSION_FILE
            except Exception as e:
                logger.warning(f"Could not load session: {e}")
        return None

    def save_session_state(self):
        """Save browser session for future runs"""
        if SAVE_SESSION and self.context:
            try:
                self.context.storage_state(path=SESSION_FILE)
                logger.info(f"💾 Session saved to {SESSION_FILE}")
            except Exception as e:
                logger.warning(f"Could not save session: {e}")

    def setup_browser(self):
        """Initialize Playwright and browser"""
        logger.info("🌐 Setting up browser...")
        self.playwright = sync_playwright().start()

        # Launch browser (Chrome-based for better compatibility)
        self.browser = self.playwright.chromium.launch(
            headless=HEADLESS,
            args=[
                '--disable-blink-features=AutomationControlled',
            ]
        )

        # Check if we have a saved session
        session_path = self.load_session()

        # Create context with realistic settings and optional session restore
        context_options = {
            'viewport': {'width': 1920, 'height': 1080},
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        if session_path:
            context_options['storage_state'] = session_path
            logger.info("✓ Loaded saved session (may skip login)")

        self.context = self.browser.new_context(**context_options)

        self.page = self.context.new_page()
        logger.info("✓ Browser ready")

    def login(self):
        """Login to TikTok account"""
        logger.info(f"🔐 Logging in to TikTok (method: {LOGIN_METHOD})...")

        if LOGIN_METHOD == 'google':
            self._login_with_google()
        else:
            self._login_with_email()

    def _login_with_email(self):
        """Login using email/username and password"""
        # Navigate to TikTok email login page
        self.page.goto('https://www.tiktok.com/login/phone-or-email/email')

        # Wait a bit for page to load
        time.sleep(3)

        try:
            # Try to find and fill login form
            # TikTok's selectors can change, so we'll try multiple approaches

            # Look for email/username input
            username_input = self.page.locator('input[name="username"]').first
            if username_input.count() == 0:
                # Alternative selector
                username_input = self.page.locator('input[type="text"]').first

            username_input.fill(TIKTOK_USERNAME)
            time.sleep(1)

            # Look for password input
            password_input = self.page.locator('input[type="password"]').first
            password_input.fill(TIKTOK_PASSWORD)
            time.sleep(1)

            # Click login button
            login_button = self.page.locator('button[type="submit"]').first
            if login_button.count() == 0:
                # Alternative - look for button with "Log in" text
                login_button = self.page.get_by_role('button', name='Log in')

            login_button.click()

            # Wait for navigation or 2FA prompt
            logger.info("⏳ Waiting for login to complete...")
            logger.info("   (If 2FA is enabled, please complete it in the browser)")
            logger.info("   (Checking for Messages in sidebar as login indicator)")

            # Wait for either successful login or stay on page for manual intervention
            time.sleep(5)

            # Check if we're logged in by looking for Messages in the left sidebar
            # Messages menu item only appears when logged in
            try:
                # Try multiple selectors for the Messages menu item
                messages_selectors = [
                    'text=Messages',  # Text content
                    '[href*="/messages"]',  # Link to messages
                    'a:has-text("Messages")',  # Link containing Messages text
                ]

                logged_in = False
                for selector in messages_selectors:
                    try:
                        self.page.wait_for_selector(selector, timeout=25000)
                        logged_in = True
                        break
                    except PlaywrightTimeoutError:
                        continue

                if logged_in:
                    logger.info("✓ Login successful! (Messages menu detected)")
                else:
                    raise PlaywrightTimeoutError("Messages menu not found")

            except PlaywrightTimeoutError:
                logger.info("⚠️  Please complete login manually if needed (2FA, captcha, etc.)")
                logger.info("   Press Enter when logged in (check if Messages appears in sidebar)...")
                input()

        except Exception as e:
            logger.info(f"⚠️  Login form interaction failed: {e}")
            logger.info("   Please log in manually in the browser window")
            logger.info("   Press Enter when logged in...")
            input()

    def _login_with_google(self):
        """Login using Google OAuth"""
        # Navigate to TikTok main login page
        self.page.goto('https://www.tiktok.com/login')

        # Wait a bit for page to load
        time.sleep(3)

        # First, check if we're already logged in from a saved session
        logger.info("   Checking if already logged in from saved session...")
        try:
            # Check for Messages menu (indicates logged in)
            messages_selectors = [
                'text=Messages',
                '[href*="/messages"]',
                'a:has-text("Messages")',
            ]

            already_logged_in = False
            for selector in messages_selectors:
                try:
                    self.page.wait_for_selector(selector, timeout=5000)
                    already_logged_in = True
                    break
                except PlaywrightTimeoutError:
                    continue

            if already_logged_in:
                logger.info("✓ Already logged in from saved session!")
                return
        except Exception:
            pass

        try:
            # Look for "Continue with Google" button
            # TikTok may use different selectors, try multiple approaches
            logger.info("   Looking for 'Continue with Google' button...")

            google_button = None

            # Try finding by text content
            try:
                google_button = self.page.get_by_text('Continue with Google', exact=False).first
                if google_button.count() == 0:
                    google_button = None
            except Exception:
                pass

            # Try finding by role and name
            if not google_button:
                try:
                    google_button = self.page.get_by_role('link', name='Google').first
                    if google_button.count() == 0:
                        google_button = None
                except Exception:
                    pass

            # Try finding by common OAuth selectors
            if not google_button:
                try:
                    # Look for SVG or icon with Google branding
                    google_button = self.page.locator('[aria-label*="Google"], [title*="Google"]').first
                    if google_button.count() == 0:
                        google_button = None
                except Exception:
                    pass

            # If no Google button found, might already be logged in
            if not google_button or google_button.count() == 0:
                logger.info("   Google login button not found - checking if already logged in...")
                time.sleep(5)

                # Check for Messages menu again
                try:
                    messages_selectors = [
                        'text=Messages',
                        '[href*="/messages"]',
                        'a:has-text("Messages")',
                    ]

                    already_logged_in = False
                    for selector in messages_selectors:
                        try:
                            self.page.wait_for_selector(selector, timeout=5000)
                            already_logged_in = True
                            break
                        except PlaywrightTimeoutError:
                            continue

                    if already_logged_in:
                        logger.info("✓ Already logged in from previous session!")
                        return
                    else:
                        raise Exception("Could not find 'Continue with Google' button and not logged in")
                except Exception as e:
                    raise Exception(f"Could not find 'Continue with Google' button: {e}")

            if google_button and google_button.count() > 0:
                logger.info("   Found Google login button, clicking...")
                google_button.click()
                time.sleep(3)

                # Now we should be on Google's OAuth page
                logger.info("   Please complete Google sign-in in the browser...")
                logger.info("   This includes:")
                logger.info("   - Selecting your Google account")
                logger.info("   - Entering password if needed")
                logger.info("   - Completing 2FA if enabled")
                logger.info("   - Granting permissions to TikTok")

                # Wait for redirect back to TikTok after OAuth
                logger.info("⏳ Waiting for OAuth to complete...")
                logger.info("   (Checking for Messages in sidebar as login indicator)")

                # Check if we're logged in by looking for Messages in the left sidebar
                # Messages menu item only appears when logged in
                try:
                    # Try multiple selectors for the Messages menu item
                    messages_selectors = [
                        'text=Messages',  # Text content
                        '[href*="/messages"]',  # Link to messages
                        'a:has-text("Messages")',  # Link containing Messages text
                    ]

                    logged_in = False
                    for selector in messages_selectors:
                        try:
                            self.page.wait_for_selector(selector, timeout=30000)
                            logged_in = True
                            break
                        except PlaywrightTimeoutError:
                            continue

                    if logged_in:
                        logger.info("✓ Login successful! (Messages menu detected)")
                    else:
                        raise PlaywrightTimeoutError("Messages menu not found")

                except PlaywrightTimeoutError:
                    logger.info("⚠️  OAuth flow taking longer than expected")
                    logger.info("   Press Enter when logged in (check if Messages appears in sidebar)...")
                    input()

            else:
                raise Exception("Could not find 'Continue with Google' button")

        except Exception as e:
            logger.info(f"⚠️  Google login failed: {e}")
            logger.info("   Please complete login manually in the browser window")
            logger.info("   Steps:")
            logger.info("   1. Click 'Continue with Google'")
            logger.info("   2. Select your Google account")
            logger.info("   3. Complete authentication")
            logger.info("   Press Enter when logged in...")
            input()

    def navigate_to_following(self):
        """Open the following modal"""
        logger.info("📍 Opening following modal...")

        try:
            # Try to get current user's username by clicking profile button
            try:
                logger.info("   Looking for Profile button...")

                # Try multiple selectors to find the Profile button
                profile_button = None

                # Try by text "Profile"
                try:
                    profile_button = self.page.get_by_text('Profile', exact=True).first
                    if profile_button.count() == 0:
                        profile_button = None
                except Exception:
                    pass

                # Try by data-e2e attribute
                if not profile_button:
                    try:
                        profile_button = self.page.locator('[data-e2e="profile-icon"]').first
                        if profile_button.count() == 0:
                            profile_button = None
                    except Exception:
                        pass

                # Try by class pattern with Profile label
                if not profile_button:
                    try:
                        profile_button = self.page.locator('.TUXButton-label:has-text("Profile")').first
                        if profile_button.count() > 0:
                            # Click the parent button instead of the label
                            profile_button = profile_button.locator('..').first
                        else:
                            profile_button = None
                    except Exception:
                        pass

                if profile_button and profile_button.count() > 0:
                    logger.info("   Found Profile button, clicking...")
                    profile_button.click()
                    time.sleep(3)

                    # Get the profile URL for logging
                    current_url = self.page.url
                    logger.info(f"   On profile: {current_url}")
                else:
                    raise Exception("Could not find Profile button with any selector")

            except Exception as e:
                logger.info(f"   Could not navigate via profile button: {e}")
                logger.info("   Please click on your Profile button manually")
                logger.info("   Press Enter when you're on your profile page...")
                input()

            # Look for the Following button and click it to open the modal
            logger.info("   Looking for Following button...")
            modal_opened = False

            # Primary: Try the data-e2e="following" selector
            try:
                following_element = self.page.locator('[data-e2e="following"]').first
                if following_element.count() > 0:
                    logger.info("   Found Following button via data-e2e attribute, clicking...")
                    following_element.click()
                    modal_opened = True
                    time.sleep(2)
            except Exception as e:
                logger.info(f"   Could not click via data-e2e selector: {e}")

            # Fallback: Try text-based search
            if not modal_opened:
                try:
                    following_element = self.page.get_by_text('Following', exact=False).first
                    if following_element.count() > 0:
                        logger.info("   Found Following button via text search, clicking...")
                        following_element.click()
                        modal_opened = True
                        time.sleep(2)
                except Exception as e:
                    logger.info(f"   Could not click via text search: {e}")

            # Additional fallback selectors
            if not modal_opened:
                following_selectors = [
                    '[data-e2e="following-count"]',
                    'strong[title="Following"]',
                    '//strong[@title="Following"]/..',
                ]

                for selector in following_selectors:
                    try:
                        if selector.startswith('//'):
                            element = self.page.locator(f'xpath={selector}').first
                        else:
                            element = self.page.locator(selector).first

                        if element.count() > 0:
                            logger.info(f"   Found Following button via fallback selector, clicking...")
                            element.click()
                            modal_opened = True
                            time.sleep(2)
                            break
                    except Exception as e:
                        continue

            if not modal_opened:
                raise Exception("Could not find Following button with any selector")

            # Wait for the modal to appear
            logger.info("   Waiting for modal to open...")
            try:
                modal = self.page.locator('[role="dialog"][data-e2e="follow-info-popup"]')
                modal.wait_for(state='visible', timeout=10000)
                logger.info("✓ Following modal opened successfully!")

                # Click on the "Following" tab within the modal to show the following list
                # The modal has tabs: Following, Followers, Friends, Suggested
                logger.info("   Clicking 'Following' tab in modal...")
                time.sleep(1)

                # Try to find and click the Following tab
                following_tab_clicked = False
                try:
                    # Look for the tab containing "Following" text within the modal
                    # The tab structure has div with text "Following" and strong with count
                    following_tab_selectors = [
                        # Look for div containing both "Following" text and a count
                        '//div[contains(@class, "DivTabItem") and .//div[text()="Following"]]',
                        # Alternative: look for any clickable element with "Following" in the tabs area
                        '//div[contains(@class, "DivTabs")]//div[text()="Following"]/..',
                    ]

                    for selector in following_tab_selectors:
                        try:
                            tab = modal.locator(f'xpath={selector}').first
                            if tab.count() > 0:
                                tab.click()
                                following_tab_clicked = True
                                time.sleep(1)
                                logger.info("   ✓ Clicked on Following tab")
                                break
                        except Exception:
                            continue

                    if not following_tab_clicked:
                        logger.info("   ⚠️  Could not auto-click Following tab, may already be selected")

                except Exception as e:
                    logger.info(f"   ⚠️  Error clicking Following tab: {e}")
                    logger.info("   Continuing anyway - tab may already be selected")

            except PlaywrightTimeoutError:
                logger.info("⚠️  Modal did not appear as expected")
                raise ValueError("Following modal did not open")

        except Exception as e:
            logger.info(f"⚠️  Could not open following modal: {e}")
            logger.info("   Please open the following modal manually:")
            logger.info("   1. Make sure you're on your profile")
            logger.info("   2. Click on your 'Following' count number")
            logger.info("   3. Wait for the popup to appear")
            logger.info("   4. Click on the 'Following' tab in the modal")
            logger.info("   Press Enter when the modal is open and Following tab is selected...")
            input()

    def validate_on_following_page(self):
        """Validate that the following modal is open"""
        try:
            # Check if the modal dialog is visible
            modal = self.page.locator('[role="dialog"][data-e2e="follow-info-popup"]')
            if modal.count() > 0 and modal.is_visible():
                return True
            else:
                logger.info(f"⚠️  Warning: Following modal is not visible")
                return False
        except Exception as e:
            logger.info(f"⚠️  Error checking for modal: {e}")
            return False

    def scroll_and_load_followers(self):
        """Scroll through the modal's followers list to load all of them"""
        if MAX_FOLLOWERS_TO_REVIEW > 0:
            logger.info(f"📜 Loading followers from modal (limited to {MAX_FOLLOWERS_TO_REVIEW})...")
        else:
            logger.info("📜 Loading all followers from modal...")

        # Validate the modal is open
        if not self.validate_on_following_page():
            logger.info("   Please ensure the Following modal is open")
            logger.info("   Press Enter to continue anyway, or Ctrl+C to abort...")
            try:
                input()
            except KeyboardInterrupt:
                raise

        previous_count = 0
        no_change_count = 0
        max_attempts = 10  # Maximum scroll attempts if nothing loads

        while True:
            # Scroll within the modal's user list container
            # The modal contains a scrollable div with the user list
            self.page.evaluate('''
                () => {
                    // Find the modal dialog
                    const modal = document.querySelector('[role="dialog"][data-e2e="follow-info-popup"]');
                    if (!modal) return;

                    // Find the scrollable container within the modal
                    // Try multiple selectors based on the HTML structure
                    const scrollContainer =
                        modal.querySelector('[class*="DivUserListContainer"]') ||
                        modal.querySelector('[class*="UserListContainer"]') ||
                        modal.querySelector('div[class*="es9zqxz0"]') ||  // Specific class from HTML
                        modal.querySelector('div > ul') ||
                        modal;

                    if (scrollContainer) {
                        scrollContainer.scrollTop = scrollContainer.scrollHeight;
                    }
                }
            ''')

            time.sleep(2)

            # Count current followers loaded (look within the modal)
            # User items are <li> elements containing user info
            modal = self.page.locator('[role="dialog"][data-e2e="follow-info-popup"]')
            followers = modal.locator('li').count()

            # Alternative: try to count by user container class
            if followers == 0:
                followers = modal.locator('[class*="DivUserContainer"]').count()

            logger.info(f"   Loaded {followers} accounts...")

            # Check if we've reached the user-defined limit
            if MAX_FOLLOWERS_TO_REVIEW > 0 and followers >= MAX_FOLLOWERS_TO_REVIEW:
                logger.info(f"✓ Reached review limit. Total: {followers} accounts")
                break

            if followers == previous_count:
                no_change_count += 1
                if no_change_count >= 3:
                    logger.info(f"✓ Finished loading. Total: {followers} accounts")
                    break
            else:
                no_change_count = 0

            previous_count = followers

            # Safety check - if we've loaded a very large number, break
            if followers > 15000:
                logger.info("⚠️  Loaded over 15,000 accounts. Stopping scroll.")
                break

            # Safety check - if nothing loads after multiple attempts
            if followers == 0 and no_change_count >= max_attempts:
                logger.info("⚠️  No followers found after multiple attempts.")
                logger.info("   Please verify the Following modal is open and you have followers.")
                break

        return followers

    def check_if_account_invalid(self, username):
        """
        Check if an account is banned, deleted, or has no videos by visiting their profile.
        Returns (is_invalid, reason)
        """
        try:
            # Quick check: Auto-remove accounts with "user" prefix (default TikTok usernames)
            if username.lower().startswith('user'):
                logger.info(f"      ❌ Auto-flagged: Username starts with 'user' (default/spam account)")
                return True, "Default username format (userXXXX)"

            # Navigate to the user's profile
            profile_url = f"https://www.tiktok.com/@{username}"
            logger.info(f"      Checking profile: {profile_url}")

            self.page.goto(profile_url, timeout=30000)
            time.sleep(3)

            # Secondary check: Look for Refresh button (indicates page load issue, not invalid account)
            try:
                refresh_button = self.page.get_by_text('Refresh', exact=False).first
                if refresh_button.count() > 0:
                    logger.info(f"      ⚠️  Found Refresh button - page may not have loaded properly")
                    logger.info(f"      Clicking Refresh and retrying...")
                    refresh_button.click()
                    time.sleep(3)
            except Exception:
                pass

            # Get page text after potential refresh
            page_text = self.page.inner_text('body').lower()

            # Check again for Refresh button after waiting - if still there, skip this account
            try:
                refresh_button = self.page.get_by_text('Refresh', exact=False).first
                if refresh_button.count() > 0:
                    logger.info(f"      ⚠️  Refresh button still present - skipping to avoid false positive")
                    return False, None  # Mark as valid to avoid false positive
            except Exception:
                pass

            # Check for "Couldn't find this account" message
            if "couldn't find this account" in page_text or "couldn't find this account" in page_text:
                return True, "Account not found"

            if "account not found" in page_text:
                return True, "Account not found"

            if "banned" in page_text and "account" in page_text:
                return True, "Banned account"

            # Check for videos on the profile
            # Look for video count or video elements
            try:
                # Try to find video count indicator
                # TikTok shows video count on profile, look for common selectors
                video_count_selectors = [
                    '[data-e2e="user-post-item"]',  # Individual video items
                    '[class*="DivItemContainer"]',  # Video container
                    'div[data-e2e="user-post-item-list"] > div',  # Videos in the list
                ]

                has_videos = False
                for selector in video_count_selectors:
                    try:
                        video_elements = self.page.locator(selector)
                        count = video_elements.count()
                        if count > 0:
                            logger.info(f"      Found {count} videos")
                            has_videos = True
                            break
                    except Exception:
                        continue

                if not has_videos:
                    # Also check for "No content" or empty state messages
                    if "no content" in page_text or "hasn't posted" in page_text:
                        return True, "No videos (likely deleted/banned)"
                    # If we can't find videos but also no error message, mark as invalid
                    return True, "No videos found"

                # Account has videos, it's valid
                return False, None

            except Exception as e:
                logger.info(f"      Error checking for videos: {e}")
                # If we can't determine, assume valid to avoid false positives
                return False, None

        except Exception as e:
            logger.info(f"      Error checking account {username}: {e}")
            # On error, default to NOT invalid to avoid false positives
            return False, None

    def unfollow_invalid_accounts(self):
        """Find and unfollow banned/deleted accounts by checking their profiles"""
        logger.info("🔍 Scanning for banned/deleted accounts by checking profiles...")

        # Get all follower elements from within the modal
        modal = self.page.locator('[role="dialog"][data-e2e="follow-info-popup"]')

        # Get follower list items within the modal
        follower_elements = modal.locator('li').all()

        if len(follower_elements) == 0:
            logger.info("⚠️  No followers loaded in modal. Cannot scan for invalid accounts.")
            return 0

        # First, extract all usernames from the modal
        logger.info(f"   Extracting usernames from {len(follower_elements)} accounts...")
        usernames = []
        skipped_count = 0

        for idx, element in enumerate(follower_elements):
            try:
                # Get username - use the unique ID (e.g., @username)
                username = None
                try:
                    # Try to find the username element with class containing "PUniqueId"
                    username_elem = element.locator('[class*="PUniqueId"]').first
                    if username_elem.count() > 0:
                        username = username_elem.inner_text().strip()

                    # Fallback: try data-e2e attribute
                    if not username:
                        username_elem = element.locator('[data-e2e="following-username"]')
                        if username_elem.count() > 0:
                            username = username_elem.inner_text().strip()
                except (PlaywrightTimeoutError, Exception) as e:
                    logger.info(f"   Could not extract username for account {idx}: {e}")

                if username and username not in ['@', '@_']:
                    # Remove @ symbol if present
                    username_clean = username.lstrip('@')

                    # Skip if already processed
                    if username in self.state['processed_accounts']:
                        skipped_count += 1
                        if idx < 10:
                            logger.info(f"   Account {idx}: {username} - already processed (skipped)")
                        continue

                    usernames.append({'username': username, 'username_clean': username_clean, 'index': idx})

            except Exception as e:
                logger.info(f"   Error extracting username for account {idx}: {e}")
                continue

        logger.info(f"   Extracted {len(usernames)} usernames to check ({skipped_count} already processed)")

        # Now check each account by visiting their profile
        invalid_accounts = []

        for i, account_info in enumerate(usernames):
            username = account_info['username']
            username_clean = account_info['username_clean']
            idx = account_info['index']

            try:
                logger.info(f"   [{i+1}/{len(usernames)}] Checking {username}...")

                # Check if account is invalid by visiting profile
                is_invalid, reason = self.check_if_account_invalid(username_clean)

                if is_invalid:
                    logger.info(f"      ❌ INVALID: {reason}")
                    invalid_accounts.append({
                        'username': username,
                        'index': idx,
                        'reason': reason
                    })
                else:
                    logger.info(f"      ✓ Valid account")

                # Mark as processed
                self.state['processed_accounts'].append(username)
                self.save_state()

                # Add delay between profile checks to avoid bot detection
                # Add some randomization (±25%) to make it more human-like
                if i < len(usernames) - 1:  # Don't delay after the last account
                    randomized_delay = PROFILE_CHECK_DELAY + random.randint(-int(PROFILE_CHECK_DELAY * 0.25), int(PROFILE_CHECK_DELAY * 0.25))
                    logger.info(f"      ⏰ Waiting {randomized_delay} seconds before next check (avoiding bot detection)...")
                    time.sleep(randomized_delay)

            except Exception as e:
                logger.info(f"   Error checking account {username}: {e}")
                continue

        logger.info(f"✓ Found {len(invalid_accounts)} invalid accounts out of {len(usernames)} checked")

        # Export to CSV
        if invalid_accounts:
            self.export_to_csv(invalid_accounts)

        # Navigate back to Following modal before unfollowing
        if invalid_accounts:
            logger.info("📍 Navigating back to Following modal to unfollow invalid accounts...")
            self.navigate_to_following()
            time.sleep(2)

            # Unfollow invalid accounts with rate limiting
            self.unfollow_batch(invalid_accounts)

        return len(invalid_accounts)

    def unfollow_batch(self, accounts):
        """Unfollow accounts in a batch with rate limiting"""
        batch_size = min(BATCH_SIZE, len(accounts))

        if DRY_RUN:
            logger.info(f"🧪 DRY RUN MODE: Would unfollow {batch_size} accounts (limited to {BATCH_SIZE} per session)...")
            logger.info(f"   No accounts will actually be unfollowed. Set DRY_RUN=false in .env to unfollow.")
        else:
            logger.info(f"🚫 Unfollowing {batch_size} accounts (limited to {BATCH_SIZE} per session)...")

        unfollowed = 0
        for account in accounts[:batch_size]:
            try:
                username = account['username']
                account_index = account['index']

                # Check if we've already processed this account
                if username in self.state['processed_accounts']:
                    logger.info(f"   Skipping {username} (already processed)")
                    continue

                # Re-query the element from modal to avoid stale element issues
                # Elements can become stale after page changes
                try:
                    modal = self.page.locator('[role="dialog"][data-e2e="follow-info-popup"]')
                    follower_items = modal.locator('li')

                    if account_index >= follower_items.count():
                        logger.info(f"   ⚠️  Account index out of range for: {username}")
                        continue

                    element = follower_items.nth(account_index)
                except Exception as e:
                    logger.info(f"   ⚠️  Could not re-query element for {username}: {e}")
                    continue

                # Find and click the following/unfollow button
                # The button has data-e2e="follow-button" and text "Following"
                try:
                    # Try the data-e2e selector first
                    unfollow_button = element.locator('button[data-e2e="follow-button"]').first

                    # Fallback: filter by text
                    if unfollow_button.count() == 0:
                        unfollow_button = element.locator('button').filter(has_text='Following').first

                    if unfollow_button.count() > 0:
                        # Scroll element into view
                        element.scroll_into_view_if_needed()
                        time.sleep(1)

                        if DRY_RUN:
                            # Dry run mode - don't actually click
                            logger.info(f"   🧪 Would unfollow: {username}")
                        else:
                            # Click unfollow
                            unfollow_button.click()
                            time.sleep(ACTION_DELAY)
                            logger.info(f"   ✓ Unfollowed: {username}")

                        # Track in state (even in dry run, to avoid re-scanning same accounts)
                        self.state['processed_accounts'].append(username)
                        if not DRY_RUN:
                            self.state['unfollowed_accounts'].append({
                                'username': username,
                                'timestamp': datetime.now().isoformat()
                            })
                        self.save_state()

                        unfollowed += 1
                    else:
                        logger.info(f"   ⚠️  Could not find unfollow button for: {username}")
                except PlaywrightTimeoutError:
                    logger.info(f"   ⚠️  Timeout finding unfollow button for: {username}")
                    continue

            except Exception as e:
                logger.info(f"   Error unfollowing {account['username']}: {e}")
                continue

        logger.info(f"✓ Unfollowed {unfollowed} accounts this session")

        # Update last run time
        self.state['last_run'] = datetime.now().isoformat()
        self.save_state()

        # Calculate next run time
        next_run = datetime.now() + timedelta(seconds=UNFOLLOW_DELAY)
        logger.info(f"⏰ Next run scheduled for: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"   ({UNFOLLOW_DELAY/3600:.1f} hours from now)")

    def cleanup(self):
        """Clean up browser resources"""
        try:
            if self.context:
                self.context.close()
        except Exception as e:
            logger.info(f"   Warning: Error closing context: {e}")

        try:
            if self.browser:
                self.browser.close()
        except Exception as e:
            logger.info(f"   Warning: Error closing browser: {e}")

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            logger.info(f"   Warning: Error stopping playwright: {e}")

    def run(self):
        """Main execution flow"""
        try:
            # Validate credentials based on login method
            if LOGIN_METHOD == 'email':
                if not TIKTOK_USERNAME or not TIKTOK_PASSWORD:
                    logger.info("❌ Error: Please set TIKTOK_USERNAME and TIKTOK_PASSWORD in .env file")
                    logger.info("   (Required for email login method)")
                    return
            # For Google login, credentials are handled through OAuth (no need to check)

            if not self.should_run():
                return

            self.setup_browser()
            self.login()
            # Save session after successful login
            self.save_session_state()
            self.navigate_to_following()
            self.scroll_and_load_followers()
            self.unfollow_invalid_accounts()

            logger.info("\n✅ Script completed successfully!")
            logger.info(f"📊 Total accounts unfollowed: {len(self.state['unfollowed_accounts'])}")

        except KeyboardInterrupt:
            logger.info("\n\n⚠️  Script interrupted by user (Ctrl+C)")
            logger.info("   Progress has been saved. You can run the script again later.")
            return

        except Exception as e:
            logger.info(f"\n❌ Error occurred: {e}")
            import traceback
            traceback.print_exc()
            return

        finally:
            if self.browser or self.context or self.playwright:
                logger.info("\n🔄 Closing browser...")
                time.sleep(1)
                self.cleanup()


def main():
    logger.info("=" * 60)
    logger.info("TikTok Follower Cleanup Script")
    logger.info("=" * 60)

    if DRY_RUN:
        logger.info("")
        logger.info("🧪 " + "=" * 56)
        logger.info("🧪 DRY RUN MODE - NO ACCOUNTS WILL BE UNFOLLOWED")
        logger.info("🧪 Set DRY_RUN=false in .env to actually unfollow")
        logger.info("🧪 " + "=" * 56)

    logger.info("")

    unfollower = TikTokUnfollower()
    unfollower.run()


if __name__ == '__main__':
    main()
