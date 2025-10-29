# TikTok Follower Cleanup Script

Automatically unfollow banned or deleted accounts from your TikTok followers list with intelligent rate limiting to avoid hitting TikTok's limits.

## Problem

TikTok has a 10,000 follower limit, but doesn't automatically remove banned or deleted accounts. This script helps you clean up those inactive accounts to make room for new followers.

## Features

- 🔐 Automated login with MFA/2FA support
- 🔍 Scans all your followers for banned/deleted accounts
- 🚫 Automatically unfollows invalid accounts
- ⏰ Rate limiting (default: 5 unfollows every 3 hours)
- 💾 State persistence (resumes where it left off)
- 🛡️ Safe delays to avoid detection

## Requirements

- Python 3.7+
- Windows OS (or any OS with GUI for browser automation)
- Active TikTok account

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
TIKTOK_USERNAME=your_username_or_email
TIKTOK_PASSWORD=your_password

# Optional: Adjust rate limiting (defaults shown)
UNFOLLOW_DELAY=10800  # 3 hours between batches
BATCH_SIZE=5          # Accounts to unfollow per batch
ACTION_DELAY=5        # Seconds between individual unfollows
HEADLESS=false        # Set to true for background operation
```

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
| `TIKTOK_USERNAME` | - | Your TikTok username or email |
| `TIKTOK_PASSWORD` | - | Your TikTok password |
| `UNFOLLOW_DELAY` | 10800 | Seconds between batches (3 hours) |
| `BATCH_SIZE` | 5 | Accounts to unfollow per session |
| `ACTION_DELAY` | 5 | Seconds between individual unfollows |
| `HEADLESS` | false | Run browser in background |

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

## Safety & Best Practices

- ✅ Start with conservative settings (small batch size, long delays)
- ✅ Monitor first few runs to ensure proper operation
- ✅ Keep `HEADLESS=false` initially to watch what's happening
- ✅ Don't share your `.env` file (contains credentials)
- ⚠️ Use at your own risk - automated actions may violate TikTok's ToS
- ⚠️ TikTok may implement countermeasures against automation

## Files

- `tiktok_unfollower.py` - Main script
- `requirements.txt` - Python dependencies
- `.env` - Your configuration (create from `.env.example`)
- `state.json` - Persistent state (auto-generated)
- `.gitignore` - Prevents committing sensitive files

## License

Use at your own risk. This is for educational purposes.
