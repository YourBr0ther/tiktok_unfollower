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

            # Wait for either successful login or stay on page for manual intervention
            time.sleep(10)

            # Check if we're logged in by looking for user profile indicators
            try:
                # Wait for profile avatar or similar element that indicates login
                self.page.wait_for_selector('[data-e2e="profile-icon"]', timeout=30000)
                print("✓ Login successful!")
            except PlaywrightTimeoutError:
                print("⚠️  Please complete login manually if needed (2FA, captcha, etc.)")
                print("   Press Enter when logged in...")
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

                # Check if we're logged in
                try:
                    self.page.wait_for_selector('[data-e2e="profile-icon"]', timeout=60000)
                    print("✓ Login successful!")
                except PlaywrightTimeoutError:
                    print("⚠️  OAuth flow taking longer than expected")
                    print("   Press Enter when logged in...")
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
        """Navigate to the following page"""
        print("📍 Navigating to following page...")

        # Get current username from profile
        try:
            # Click on profile icon
            self.page.click('[data-e2e="profile-icon"]')
            time.sleep(2)

            # Get the profile URL from current page
            current_url = self.page.url

            # Extract username from URL
            # Expected format: https://www.tiktok.com/@username or similar
            if '@' not in current_url:
                raise ValueError("Could not find username in URL (no @ symbol)")

            username = current_url.split('@')[-1].split('/')[0].split('?')[0]

            if not username or len(username) < 2:
                raise ValueError(f"Invalid username extracted: {username}")

            # Navigate to following page
            following_url = f'https://www.tiktok.com/@{username}/following'
            self.page.goto(following_url)
            time.sleep(3)

            print(f"✓ On following page: {following_url}")
        except Exception as e:
            print(f"⚠️  Could not auto-navigate: {e}")
            print("   Please navigate to your Following page manually")
            print("   Press Enter when ready...")
            input()

    def validate_on_following_page(self):
        """Validate that we're on the following page"""
        current_url = self.page.url

        # Check if URL contains "following"
        if '/following' not in current_url.lower():
            print(f"⚠️  Warning: Current URL doesn't appear to be a following page")
            print(f"   Current URL: {current_url}")
            return False

        return True

    def scroll_and_load_followers(self):
        """Scroll through followers list to load all of them"""
        print("📜 Loading all followers...")

        # Validate we're on the right page
        if not self.validate_on_following_page():
            print("   Please ensure you're on the Following page")
            print("   Press Enter to continue anyway, or Ctrl+C to abort...")
            try:
                input()
            except KeyboardInterrupt:
                raise

        previous_count = 0
        no_change_count = 0
        max_attempts = 10  # Maximum scroll attempts if nothing loads

        while True:
            # Scroll to bottom of the followers list
            self.page.evaluate('''
                () => {
                    const scrollContainer = document.querySelector('[data-e2e="following-item-list"]') ||
                                          document.querySelector('.following-list') ||
                                          window;
                    if (scrollContainer) {
                        scrollContainer.scrollTo(0, scrollContainer.scrollHeight || document.body.scrollHeight);
                    }
                }
            ''')

            time.sleep(2)

            # Count current followers loaded
            followers = self.page.locator('[data-e2e="following-item"]').count()
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
                print("   Please verify you're on the following page and have followers.")
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
        """Find and unfollow banned/deleted accounts"""
        print("🔍 Scanning for banned/deleted accounts...")

        # Get all follower elements
        follower_elements = self.page.locator('[data-e2e="following-item"]').all()

        if len(follower_elements) == 0:
            print("⚠️  No followers loaded. Cannot scan for invalid accounts.")
            return 0

        invalid_accounts = []

        # Scan through all followers
        for idx, element in enumerate(follower_elements):
            try:
                # Get username for logging
                username = "Unknown"
                try:
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

                # Re-query the element to avoid stale element issues
                # Elements can become stale after page changes
                try:
                    follower_items = self.page.locator('[data-e2e="following-item"]')
                    if account_index >= follower_items.count():
                        print(f"   ⚠️  Account index out of range for: {username}")
                        continue

                    element = follower_items.nth(account_index)
                except Exception as e:
                    print(f"   ⚠️  Could not re-query element for {username}: {e}")
                    continue

                # Find and click the following/unfollow button
                # The button typically says "Following" and changes to "Follow" after clicking
                try:
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
