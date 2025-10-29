# TikTok Follower Cleanup Script

Automatically unfollow banned or deleted accounts from your TikTok followers list with intelligent rate limiting to avoid hitting TikTok's limits.

## Problem

TikTok has a 10,000 follower limit, but doesn't automatically remove banned or deleted accounts. This script helps you clean up those inactive accounts to make room for new followers.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# 2. Configure credentials
copy .env.example .env
# Edit .env and choose login method:
#   - For email: Set LOGIN_METHOD=email and add username/password
#   - For Google: Set LOGIN_METHOD=google (no password needed)

# 3. Test run (DRY_RUN=true by default - safe mode, no unfollowing)
python tiktok_unfollower.py
# This will show you what accounts would be unfollowed without actually doing it

# 4. When ready, set DRY_RUN=false in .env and run again to actually unfollow
```

## Features

### Core Features
- 🔐 **Flexible login** - Email/password or Google OAuth support
- 🔑 **MFA/2FA support** - Human-in-the-loop for authentication
- 🔍 **Smart detection** of banned/deleted accounts
- 🚫 **Automatic unfollowing** with configurable batch sizes
- ⏰ **Intelligent rate limiting** (default: 5 unfollows every 3 hours)
- 💾 **State persistence** - resumes where it left off between runs
- 🛡️ **Safe delays** to avoid detection

### Robust Error Handling
- ✅ **Corrupted state recovery** - auto-backups and repairs broken state files
- ✅ **Configuration validation** - validates all settings with safe defaults
- ✅ **Stale element protection** - handles dynamic page changes gracefully
- ✅ **Graceful interruption** - Ctrl+C saves progress and exits cleanly
- ✅ **Resource cleanup** - properly closes all browser resources
- ✅ **Page validation** - ensures you're on the correct page before operating
- ✅ **Zero-follower detection** - handles edge cases safely

## ⚠️ Important Warnings

- **Account Safety**: Automated interactions may violate TikTok's Terms of Service. Use at your own risk.
- **Rate Limiting**: Start with conservative settings. Aggressive unfollowing may trigger TikTok's anti-bot measures.
- **Credential Security**: Never share your `.env` file. It contains your login credentials.
- **No Guarantees**: This script is provided as-is for educational purposes. The author is not responsible for any account actions taken by TikTok.

## Requirements

- Python 3.7+
- Windows OS (or any OS with GUI for browser automation)
- Active TikTok account
- Internet connection

## Setup

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Playwright Browsers

```bash
python -m playwright install chromium
```

### 3. Configure Environment Variables

Copy the example environment file and edit it with your credentials:

```bash
copy .env.example .env
```

Edit `.env` file:

```env
# Choose your login method
LOGIN_METHOD=email  # Options: 'email' or 'google'

# For email login:
TIKTOK_USERNAME=your_username_or_email
TIKTOK_PASSWORD=your_password

# For Google login:
# Leave TIKTOK_USERNAME and TIKTOK_PASSWORD empty
# You'll sign in through Google OAuth in the browser

# Optional: Adjust rate limiting (defaults shown)
UNFOLLOW_DELAY=10800  # 3 hours between batches
BATCH_SIZE=5          # Accounts to unfollow per batch
ACTION_DELAY=5        # Seconds between individual unfollows
HEADLESS=false        # Set to true for background operation
```

#### Login Methods

**Email/Password Login (`LOGIN_METHOD=email`)**
- Requires TIKTOK_USERNAME and TIKTOK_PASSWORD
- Directly fills in login form
- Supports 2FA/MFA with human intervention

**Google Login (`LOGIN_METHOD=google`)**
- Uses Google OAuth (Sign in with Google)
- No need to provide username/password in .env
- You'll complete Google authentication in the browser
- Supports all Google security features (2FA, etc.)

## Usage

### Run the Script

```bash
python tiktok_unfollower.py
```

### First Run

1. The script will open a browser window
2. It will attempt to log in automatically
3. **If MFA/2FA is enabled**: Complete the verification in the browser, then press Enter in the terminal
4. The script will navigate to your Following page
5. It will scroll and load all followers
6. It will scan for banned/deleted accounts
7. It will unfollow up to `BATCH_SIZE` accounts (default: 5)

### Subsequent Runs

The script tracks state in `state.json`:
- **Last run time**: Ensures you don't run too frequently
- **Processed accounts**: Prevents duplicate unfollowing
- **Unfollowed accounts**: History of all cleaned up accounts

Simply run the script periodically (or set up a scheduled task):

```bash
python tiktok_unfollower.py
```

If not enough time has passed, it will tell you when to run it again.

## Automation (Windows Task Scheduler)

To run automatically every few hours:

1. Open Task Scheduler
2. Create Basic Task
3. Set trigger to run every 3 hours (or your `UNFOLLOW_DELAY` value)
4. Action: Start a program
   - Program: `python.exe`
   - Arguments: `C:\path\to\tiktok_unfollower.py`
   - Start in: `C:\path\to\tiktok_unfollower`

**Note**: `HEADLESS=true` is recommended for automated runs, but you'll need to handle MFA manually on first login.

## How It Works

### Detection of Invalid Accounts

The script identifies banned/deleted accounts by:
- Looking for "banned account" text
- Checking for "account not found" messages
- Detecting missing usernames or profile information
- Identifying placeholder accounts

### Rate Limiting

To avoid TikTok's anti-automation measures:
- Only unfollows `BATCH_SIZE` accounts per run (default: 5)
- Waits `ACTION_DELAY` seconds between each unfollow (default: 5s)
- Enforces `UNFOLLOW_DELAY` between sessions (default: 3 hours)
- Uses realistic browser fingerprinting

## Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `LOGIN_METHOD` | email | Login method: 'email' or 'google' |
| `TIKTOK_USERNAME` | - | Your TikTok username or email (required for email login) |
| `TIKTOK_PASSWORD` | - | Your TikTok password (required for email login) |
| `UNFOLLOW_DELAY` | 10800 | Seconds between batches (3 hours) |
| `BATCH_SIZE` | 5 | Accounts to unfollow per session |
| `ACTION_DELAY` | 5 | Seconds between individual unfollows |
| `HEADLESS` | false | Run browser in background |
| `DRY_RUN` | true | Test mode - shows what would be unfollowed without actually doing it |

## Troubleshooting

### "Please complete login manually"

- The script detected login issues (captcha, 2FA, etc.)
- Complete the login in the browser window
- Press Enter in the terminal when done

### "Too soon to run again"

- Not enough time has passed since last run
- Check `state.json` for `last_run` timestamp
- Wait for the specified time or delete `state.json` to reset

### Selectors not working

TikTok frequently updates their UI. If the script can't find elements:
- Make sure you're using the latest version
- The script may need selector updates
- Try navigating manually when prompted

### Rate Limited by TikTok

If TikTok temporarily blocks actions:
- Increase `UNFOLLOW_DELAY` (e.g., 6 hours: 21600)
- Decrease `BATCH_SIZE` (e.g., 3 instead of 5)
- Increase `ACTION_DELAY` (e.g., 10 seconds)

## Expected Output

When running the script, you'll see output like this:

```
============================================================
TikTok Follower Cleanup Script
============================================================

🌐 Setting up browser...
✓ Browser ready
🔐 Logging in to TikTok...
⏳ Waiting for login to complete...
   (If 2FA is enabled, please complete it in the browser)
✓ Login successful!
📍 Navigating to following page...
✓ On following page: https://www.tiktok.com/@username/following
📜 Loading all followers...
   Loaded 150 accounts...
   Loaded 300 accounts...
   Loaded 450 accounts...
✓ Finished loading. Total: 450 accounts
🔍 Scanning for banned/deleted accounts...
   Found invalid account: @deleted_user123
   Found invalid account: @banned_account
   Scanned 100/450 accounts...
✓ Found 12 invalid accounts
🚫 Unfollowing 5 accounts (limited to 5 per session)...
   ✓ Unfollowed: @deleted_user123
   ✓ Unfollowed: @banned_account
   ✓ Unfollowed: @user_not_found
   ✓ Unfollowed: @invalid_user
   ✓ Unfollowed: @banned_user2
✓ Unfollowed 5 accounts this session
⏰ Next run scheduled for: 2025-10-29 16:30:00
   (3.0 hours from now)

✅ Script completed successfully!
📊 Total accounts unfollowed: 5

🔄 Closing browser...
```

## FAQ

### How often should I run this script?
The default is every 3 hours unfollowing 5 accounts at a time. This conservative approach minimizes detection risk. You can adjust `UNFOLLOW_DELAY` and `BATCH_SIZE` based on your comfort level.

### Will this get my account banned?
There's always a risk when using automation. To minimize risk:
- Use conservative rate limiting (default settings are recommended)
- Don't run it too frequently
- Monitor the first few runs manually
- Stop immediately if you receive any warnings from TikTok

### Can I run this on a schedule automatically?
Yes, you can use Windows Task Scheduler (Windows) or cron (Linux/Mac). However:
- Set `HEADLESS=true` for background operation
- You'll need to manually complete MFA on first login
- Consider saving browser session state (advanced)

### What if the script crashes or I interrupt it?
The script saves progress after each unfollow in `state.json`. You can safely interrupt with Ctrl+C and run again later. It will resume where it left off and won't re-unfollow accounts it's already processed.

### The script says "Too soon to run again"
This is the rate limiting in action. The script enforces a delay between runs (default 3 hours). You can:
- Wait until the specified time
- Delete `state.json` to reset (not recommended - you'll lose tracking)
- Adjust `UNFOLLOW_DELAY` in `.env`

### How do I know which accounts are considered "invalid"?
The script looks for:
- Accounts marked as "banned" or "banned account"
- Accounts with "account not found" or "user not found"
- Accounts with missing or placeholder usernames (e.g., just "@")
- Accounts marked as "content unavailable"

### Can I adjust the detection criteria?
Yes, but it requires modifying the `check_if_account_invalid()` function in `tiktok_unfollower.py`. The indicators list can be customized to match specific patterns you're seeing.

## Safety & Best Practices

- ✅ **Start conservative** - Use default settings for first few runs
- ✅ **Monitor initially** - Keep `HEADLESS=false` to watch what's happening
- ✅ **Check state.json** - Review what accounts were unfollowed
- ✅ **Backup credentials** - Store `.env` securely, never commit to git
- ✅ **Test on small batch** - Start with `BATCH_SIZE=1` or `2` initially
- ⚠️ **Use at own risk** - Automated actions may violate TikTok's ToS
- ⚠️ **No guarantees** - TikTok may detect and block automation
- ⚠️ **Account responsibility** - You are responsible for all actions taken

## Project Files

| File | Purpose | Auto-Generated? |
|------|---------|-----------------|
| `tiktok_unfollower.py` | Main automation script | No |
| `requirements.txt` | Python dependencies | No |
| `.env` | Your credentials & config | No (create from example) |
| `.env.example` | Configuration template | No |
| `state.json` | Tracks progress & history | Yes |
| `.gitignore` | Prevents committing secrets | No |
| `README.md` | This documentation | No |
| `PROJECT_REPORT.md` | Development summary | No |

## Development

See `PROJECT_REPORT.md` for:
- Complete development history
- Bug fixes applied
- Architecture decisions
- Testing recommendations

## License

Use at your own risk. This is for educational purposes only.
