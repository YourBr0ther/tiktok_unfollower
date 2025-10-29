#!/usr/bin/env python3
"""
TikTok Follower Cleanup Script
Automatically unfollows banned or deleted accounts from your TikTok followers list
with rate limiting to avoid hitting TikTok's limits.
"""

import os
import json
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Load environment variables
load_dotenv()

# Configuration with validation
TIKTOK_USERNAME = os.getenv('TIKTOK_USERNAME')
TIKTOK_PASSWORD = os.getenv('TIKTOK_PASSWORD')
LOGIN_METHOD = os.getenv('LOGIN_METHOD', 'email').lower()  # 'email' or 'google'

# Validate login method
if LOGIN_METHOD not in ['email', 'google']:
    print(f"⚠️  Invalid LOGIN_METHOD '{LOGIN_METHOD}', using 'email'")
    LOGIN_METHOD = 'email'

try:
    UNFOLLOW_DELAY = int(os.getenv('UNFOLLOW_DELAY', 10800))  # 3 hours default
    if UNFOLLOW_DELAY < 0:
        raise ValueError("UNFOLLOW_DELAY must be positive")
except ValueError as e:
    print(f"⚠️  Invalid UNFOLLOW_DELAY value, using default (10800 seconds): {e}")
    UNFOLLOW_DELAY = 10800

try:
    BATCH_SIZE = int(os.getenv('BATCH_SIZE', 5))
    if BATCH_SIZE < 1:
        raise ValueError("BATCH_SIZE must be at least 1")
except ValueError as e:
    print(f"⚠️  Invalid BATCH_SIZE value, using default (5): {e}")
    BATCH_SIZE = 5

try:
    ACTION_DELAY = int(os.getenv('ACTION_DELAY', 5))
    if ACTION_DELAY < 0:
        raise ValueError("ACTION_DELAY must be positive")
except ValueError as e:
    print(f"⚠️  Invalid ACTION_DELAY value, using default (5 seconds): {e}")
    ACTION_DELAY = 5

HEADLESS = os.getenv('HEADLESS', 'false').lower() == 'true'

STATE_FILE = 'state.json'


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
                print(f"⚠️  Warning: Corrupted state file ({e}). Starting fresh.")
                # Backup corrupted file
                backup_file = f'{STATE_FILE}.backup'
                try:
                    os.rename(STATE_FILE, backup_file)
                    print(f"   Old state backed up to {backup_file}")
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
            print(f"⚠️  Warning: Could not save state to {STATE_FILE}: {e}")
            # Don't raise - allow script to continue even if state save fails

    def should_run(self):
        """Check if enough time has passed since last run"""
        if not self.state['last_run']:
            return True

        last_run = datetime.fromisoformat(self.state['last_run'])
        next_run = last_run + timedelta(seconds=UNFOLLOW_DELAY)

        if datetime.now() < next_run:
            wait_time = (next_run - datetime.now()).total_seconds()
            print(f"⏰ Too soon to run again. Wait {wait_time/3600:.2f} hours")
            return False

        return True

    def setup_browser(self):
        """Initialize Playwright and browser"""
        print("🌐 Setting up browser...")
        self.playwright = sync_playwright().start()

        # Launch browser (Chrome-based for better compatibility)
        self.browser = self.playwright.chromium.launch(
            headless=HEADLESS,
            args=[
                '--disable-blink-features=AutomationControlled',
            ]
        )

        # Create context with realistic settings
        self.context = self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        self.page = self.context.new_page()
        print("✓ Browser ready")

    def login(self):
        """Login to TikTok account"""
        print(f"🔐 Logging in to TikTok (method: {LOGIN_METHOD})...")

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
            print("⏳ Waiting for login to complete...")
            print("   (If 2FA is enabled, please complete it in the browser)")
            print("   (Checking for Messages in sidebar as login indicator)")

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
                    print("✓ Login successful! (Messages menu detected)")
                else:
                    raise PlaywrightTimeoutError("Messages menu not found")

            except PlaywrightTimeoutError:
                print("⚠️  Please complete login manually if needed (2FA, captcha, etc.)")
                print("   Press Enter when logged in (check if Messages appears in sidebar)...")
                input()

        except Exception as e:
            print(f"⚠️  Login form interaction failed: {e}")
            print("   Please log in manually in the browser window")
            print("   Press Enter when logged in...")
            input()

    def _login_with_google(self):
        """Login using Google OAuth"""
        # Navigate to TikTok main login page
        self.page.goto('https://www.tiktok.com/login')

        # Wait a bit for page to load
        time.sleep(3)

        try:
            # Look for "Continue with Google" button
            # TikTok may use different selectors, try multiple approaches
            print("   Looking for 'Continue with Google' button...")

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

            if google_button and google_button.count() > 0:
                print("   Found Google login button, clicking...")
                google_button.click()
                time.sleep(3)

                # Now we should be on Google's OAuth page
                print("   Please complete Google sign-in in the browser...")
                print("   This includes:")
                print("   - Selecting your Google account")
                print("   - Entering password if needed")
                print("   - Completing 2FA if enabled")
                print("   - Granting permissions to TikTok")

                # Wait for redirect back to TikTok after OAuth
                print("⏳ Waiting for OAuth to complete...")
                print("   (Checking for Messages in sidebar as login indicator)")

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
                        print("✓ Login successful! (Messages menu detected)")
                    else:
                        raise PlaywrightTimeoutError("Messages menu not found")

                except PlaywrightTimeoutError:
                    print("⚠️  OAuth flow taking longer than expected")
                    print("   Press Enter when logged in (check if Messages appears in sidebar)...")
                    input()

            else:
                raise Exception("Could not find 'Continue with Google' button")

        except Exception as e:
            print(f"⚠️  Google login failed: {e}")
            print("   Please complete login manually in the browser window")
            print("   Steps:")
            print("   1. Click 'Continue with Google'")
            print("   2. Select your Google account")
            print("   3. Complete authentication")
            print("   Press Enter when logged in...")
            input()

    def navigate_to_following(self):
        """Open the following modal"""
        print("📍 Opening following modal...")

        try:
            # Click on profile icon to go to profile
            self.page.click('[data-e2e="profile-icon"]')
            time.sleep(3)

            # Get the profile URL
            current_url = self.page.url
            print(f"   On profile: {current_url}")

            # Look for the Following count/link and click it to open the modal
            print("   Looking for Following count...")
            modal_opened = False

            # Try multiple selectors to find and click the Following count
            following_selectors = [
                # Look for elements containing "Following" text with a count
                '//strong[@title="Following"]/..',  # XPath to parent of Following count
                '//div[contains(text(), "Following")]/following-sibling::strong/..',  # Following label + count
                '[data-e2e="following-count"]',  # If there's a data attribute
                'strong[title="Following"]',  # The count element itself
            ]

            for selector in following_selectors:
                try:
                    if selector.startswith('//'):
                        # XPath selector
                        element = self.page.locator(f'xpath={selector}').first
                    else:
                        # CSS selector
                        element = self.page.locator(selector).first

                    if element.count() > 0:
                        print(f"   Found Following count, clicking to open modal...")
                        element.click()
                        modal_opened = True
                        time.sleep(2)
                        break
                except Exception as e:
                    continue

            if not modal_opened:
                # Fallback: try to find any clickable element with "Following" text
                print("   Trying text-based search...")
                try:
                    # Look for the Following count in the tabs section
                    following_tab = self.page.locator('text=Following').first
                    if following_tab.count() > 0:
                        following_tab.click()
                        modal_opened = True
                        time.sleep(2)
                except Exception:
                    pass

            if not modal_opened:
                raise Exception("Could not find Following count to click")

            # Wait for the modal to appear
            print("   Waiting for modal to open...")
            try:
                modal = self.page.locator('[role="dialog"][data-e2e="follow-info-popup"]')
                modal.wait_for(state='visible', timeout=10000)
                print("✓ Following modal opened successfully!")
            except PlaywrightTimeoutError:
                print("⚠️  Modal did not appear as expected")
                raise ValueError("Following modal did not open")

        except Exception as e:
            print(f"⚠️  Could not open following modal: {e}")
            print("   Please open the following modal manually:")
            print("   1. Make sure you're on your profile")
            print("   2. Click on your 'Following' count number")
            print("   3. Wait for the popup to appear")
            print("   Press Enter when the modal is open...")
            input()

    def validate_on_following_page(self):
        """Validate that the following modal is open"""
        try:
            # Check if the modal dialog is visible
            modal = self.page.locator('[role="dialog"][data-e2e="follow-info-popup"]')
            if modal.count() > 0 and modal.is_visible():
                return True
            else:
                print(f"⚠️  Warning: Following modal is not visible")
                return False
        except Exception as e:
            print(f"⚠️  Error checking for modal: {e}")
            return False

    def scroll_and_load_followers(self):
        """Scroll through the modal's followers list to load all of them"""
        print("📜 Loading all followers from modal...")

        # Validate the modal is open
        if not self.validate_on_following_page():
            print("   Please ensure the Following modal is open")
            print("   Press Enter to continue anyway, or Ctrl+C to abort...")
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

            print(f"   Loaded {followers} accounts...")

            if followers == previous_count:
                no_change_count += 1
                if no_change_count >= 3:
                    print(f"✓ Finished loading. Total: {followers} accounts")
                    break
            else:
                no_change_count = 0

            previous_count = followers

            # Safety check - if we've loaded a very large number, break
            if followers > 15000:
                print("⚠️  Loaded over 15,000 accounts. Stopping scroll.")
                break

            # Safety check - if nothing loads after multiple attempts
            if followers == 0 and no_change_count >= max_attempts:
                print("⚠️  No followers found after multiple attempts.")
                print("   Please verify the Following modal is open and you have followers.")
                break

        return followers

    def check_if_account_invalid(self, account_element):
        """Check if an account is banned or deleted"""
        try:
            # Look for indicators of banned/deleted accounts
            # These accounts typically show:
            # - "Banned account" text
            # - "Account not found" text
            # - Disabled/grayed out appearance
            # - Missing profile picture or username

            text_content = account_element.inner_text().lower()

            # Check for banned or deleted indicators
            invalid_indicators = [
                'banned',
                'banned account',
                'account not found',
                'user not found',
                'this account is private',
                'content is unavailable',
            ]

            for indicator in invalid_indicators:
                if indicator in text_content:
                    return True

            # Check if username is missing or very short (potential deleted account)
            username_element = account_element.locator('[data-e2e="following-username"]')
            if username_element.count() > 0:
                username = username_element.inner_text().strip()
                # Check for just '@' or '@_' or very short/empty usernames
                if not username or username in ['@', '@_'] or len(username) <= 1:
                    return True
            else:
                # No username element found at all - likely invalid
                return True

            return False

        except Exception as e:
            print(f"   Error checking account: {e}")
            return False

    def unfollow_invalid_accounts(self):
        """Find and unfollow banned/deleted accounts in the modal"""
        print("🔍 Scanning for banned/deleted accounts in modal...")

        # Get all follower elements from within the modal
        modal = self.page.locator('[role="dialog"][data-e2e="follow-info-popup"]')

        # Get follower list items within the modal
        follower_elements = modal.locator('li').all()

        if len(follower_elements) == 0:
            print("⚠️  No followers loaded in modal. Cannot scan for invalid accounts.")
            return 0

        invalid_accounts = []

        # Scan through all followers
        for idx, element in enumerate(follower_elements):
            try:
                # Get username for logging - use the unique ID (e.g., @username)
                username = "Unknown"
                try:
                    # Try to find the username element with class containing "PUniqueId"
                    username_elem = element.locator('[class*="PUniqueId"]').first
                    if username_elem.count() > 0:
                        username = username_elem.inner_text().strip()

                    # Fallback: try data-e2e attribute
                    if username == "Unknown" or not username:
                        username_elem = element.locator('[data-e2e="following-username"]')
                        if username_elem.count() > 0:
                            username = username_elem.inner_text().strip()
                except (PlaywrightTimeoutError, Exception) as e:
                    print(f"   Could not extract username for account {idx}: {e}")

                # Check if account is invalid
                if self.check_if_account_invalid(element):
                    print(f"   Found invalid account: {username}")
                    invalid_accounts.append({
                        'username': username,
                        'index': idx
                    })

                # Progress update every 100 accounts
                if (idx + 1) % 100 == 0:
                    print(f"   Scanned {idx + 1}/{len(follower_elements)} accounts...")

            except Exception as e:
                print(f"   Error processing account {idx}: {e}")
                continue

        print(f"✓ Found {len(invalid_accounts)} invalid accounts")

        # Unfollow invalid accounts with rate limiting
        if invalid_accounts:
            self.unfollow_batch(invalid_accounts)

        return len(invalid_accounts)

    def unfollow_batch(self, accounts):
        """Unfollow accounts in a batch with rate limiting"""
        batch_size = min(BATCH_SIZE, len(accounts))

        print(f"🚫 Unfollowing {batch_size} accounts (limited to {BATCH_SIZE} per session)...")

        unfollowed = 0
        for account in accounts[:batch_size]:
            try:
                username = account['username']
                account_index = account['index']

                # Check if we've already processed this account
                if username in self.state['processed_accounts']:
                    print(f"   Skipping {username} (already processed)")
                    continue

                # Re-query the element from modal to avoid stale element issues
                # Elements can become stale after page changes
                try:
                    modal = self.page.locator('[role="dialog"][data-e2e="follow-info-popup"]')
                    follower_items = modal.locator('li')

                    if account_index >= follower_items.count():
                        print(f"   ⚠️  Account index out of range for: {username}")
                        continue

                    element = follower_items.nth(account_index)
                except Exception as e:
                    print(f"   ⚠️  Could not re-query element for {username}: {e}")
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

                        # Click unfollow
                        unfollow_button.click()
                        time.sleep(ACTION_DELAY)

                        print(f"   ✓ Unfollowed: {username}")

                        # Track in state
                        self.state['processed_accounts'].append(username)
                        self.state['unfollowed_accounts'].append({
                            'username': username,
                            'timestamp': datetime.now().isoformat()
                        })
                        self.save_state()

                        unfollowed += 1
                    else:
                        print(f"   ⚠️  Could not find unfollow button for: {username}")
                except PlaywrightTimeoutError:
                    print(f"   ⚠️  Timeout finding unfollow button for: {username}")
                    continue

            except Exception as e:
                print(f"   Error unfollowing {account['username']}: {e}")
                continue

        print(f"✓ Unfollowed {unfollowed} accounts this session")

        # Update last run time
        self.state['last_run'] = datetime.now().isoformat()
        self.save_state()

        # Calculate next run time
        next_run = datetime.now() + timedelta(seconds=UNFOLLOW_DELAY)
        print(f"⏰ Next run scheduled for: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   ({UNFOLLOW_DELAY/3600:.1f} hours from now)")

    def cleanup(self):
        """Clean up browser resources"""
        try:
            if self.context:
                self.context.close()
        except Exception as e:
            print(f"   Warning: Error closing context: {e}")

        try:
            if self.browser:
                self.browser.close()
        except Exception as e:
            print(f"   Warning: Error closing browser: {e}")

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            print(f"   Warning: Error stopping playwright: {e}")

    def run(self):
        """Main execution flow"""
        try:
            # Validate credentials based on login method
            if LOGIN_METHOD == 'email':
                if not TIKTOK_USERNAME or not TIKTOK_PASSWORD:
                    print("❌ Error: Please set TIKTOK_USERNAME and TIKTOK_PASSWORD in .env file")
                    print("   (Required for email login method)")
                    return
            # For Google login, credentials are handled through OAuth (no need to check)

            if not self.should_run():
                return

            self.setup_browser()
            self.login()
            self.navigate_to_following()
            self.scroll_and_load_followers()
            self.unfollow_invalid_accounts()

            print("\n✅ Script completed successfully!")
            print(f"📊 Total accounts unfollowed: {len(self.state['unfollowed_accounts'])}")

        except KeyboardInterrupt:
            print("\n\n⚠️  Script interrupted by user (Ctrl+C)")
            print("   Progress has been saved. You can run the script again later.")
            return

        except Exception as e:
            print(f"\n❌ Error occurred: {e}")
            import traceback
            traceback.print_exc()
            return

        finally:
            if self.browser or self.context or self.playwright:
                print("\n🔄 Closing browser...")
                time.sleep(1)
                self.cleanup()


def main():
    print("=" * 60)
    print("TikTok Follower Cleanup Script")
    print("=" * 60)
    print()

    unfollower = TikTokUnfollower()
    unfollower.run()


if __name__ == '__main__':
    main()
