# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TikTok Follower Cleanup Script - Automated tool to unfollow banned/deleted TikTok accounts using Playwright browser automation. The script uses rate limiting and state persistence to safely clean up followers without triggering TikTok's anti-bot measures.

## Common Commands

```bash
# Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# Configure credentials (first time setup)
cp .env.example .env
# Then edit .env with credentials

# Run script (DRY_RUN=true by default - safe mode)
python tiktok_unfollower.py

# Run in actual unfollow mode (after testing)
# Set DRY_RUN=false in .env, then:
python tiktok_unfollower.py
```

## Architecture

### Core Class: TikTokUnfollower

Single class design that encapsulates all functionality with the following lifecycle:

1. **State Loading** (`load_state()`) - Loads `state.json` with corrupted file recovery
2. **Browser Setup** (`setup_browser()`) - Initializes Playwright with anti-detection measures
3. **Login** (`login()`) - Supports two methods:
   - Email login (`_login_with_email()`)
   - Google OAuth (`_login_with_google()`)
4. **Navigation** (`navigate_to_following()`) - Opens TikTok's following modal (not a page, but a popup dialog)
5. **Loading** (`scroll_and_load_followers()`) - Scrolls the modal to load all followers
6. **Scanning** (`unfollow_invalid_accounts()`) - Detects banned/deleted accounts
7. **Unfollowing** (`unfollow_batch()`) - Processes accounts with rate limiting
8. **Cleanup** (`cleanup()`) - Properly closes all Playwright resources

### Key Architecture Decisions

**Modal-Based UI**: TikTok changed from a dedicated `/following` page to a modal popup. The script:
- Navigates to profile (clicks profile icon or uses current URL)
- Looks for "Following" text (e.g., "123 Following") and clicks it to open modal
- Falls back to multiple selector strategies if text search fails
- Scrolls within the modal's scrollable container (not the page)
- All follower elements are `<li>` items within `[role="dialog"][data-e2e="follow-info-popup"]`

**Stale Element Protection**: Elements are re-queried by index before each unfollow to prevent stale DOM references after clicking buttons.

**State Persistence**: After each successful unfollow, state is saved to `state.json` to:
- Prevent duplicate processing
- Track unfollowed accounts with timestamps
- Enforce rate limiting between runs
- Enable resumption after crashes

**Login Detection**: Uses presence of "Messages" menu item in the sidebar as the login success indicator (more reliable than URL-based detection).

**Two Login Methods**:
- `LOGIN_METHOD=email`: Direct form filling with TIKTOK_USERNAME/PASSWORD
- `LOGIN_METHOD=google`: OAuth flow requiring manual Google sign-in
  - **Session awareness**: Checks if already logged in from saved session before looking for login button
  - If Google button not found, waits 5 seconds and checks for Messages sidebar (indicates already logged in)

### Detection Logic (`check_if_account_invalid()`)

**Profile-Based Verification Approach:**

Instead of guessing from Following list text, the script **visits each user's profile** to verify if they exist:

1. **Extract usernames** from Following modal
2. **For each username**, navigate to `https://www.tiktok.com/@{username}`
3. **Check the profile page** for:
   - "Couldn't find this account" → Invalid
   - "Account not found" → Invalid
   - "Banned account" → Invalid
   - **No videos found** → Invalid (likely deleted/banned/fake)
   - Has videos → Valid
4. **Returns** `(is_invalid: bool, reason: str)` tuple
5. **Navigate back** to Following modal to unfollow invalid accounts

**Detection reasons** tracked for CSV export:
- "Account not found" (profile doesn't exist)
- "Banned account" (explicitly banned)
- "No videos found" (empty profile)
- "No videos (likely deleted/banned)" (profile shows "No content" or "hasn't posted")

**Important**:
- This is **slower** than text-based detection (visits each profile)
- More **accurate** - actually verifies account existence
- Use `MAX_FOLLOWERS_TO_REVIEW` to test with smaller batches
- Defaults to VALID if uncertain (conservative approach to avoid false positives)

## Configuration

Environment variables in `.env`:
- `LOGIN_METHOD` - "email" or "google" (default: email)
- `TIKTOK_USERNAME` - Required for email login
- `TIKTOK_PASSWORD` - Required for email login
- `UNFOLLOW_DELAY` - Seconds between batch runs (default: 10800 = 3 hours)
- `BATCH_SIZE` - Accounts to unfollow per run (default: 5)
- `ACTION_DELAY` - Seconds between individual unfollows (default: 5)
- `PROFILE_CHECK_DELAY` - Seconds between profile checks (default: 30, recommended: 30-60)
- `HEADLESS` - Browser visibility: true/false (default: false)
- `DRY_RUN` - Safety mode: true/false (default: true)
- `SAVE_SESSION` - Save login session to avoid re-login: true/false (default: true)
- `MAX_FOLLOWERS_TO_REVIEW` - Limit followers to load for testing (default: 0 = unlimited)

All numeric values have validation with safe fallback defaults.

## State File (`state.json`)

Auto-generated JSON tracking:
```json
{
  "last_run": "ISO-8601 timestamp",
  "processed_accounts": ["@username1", "@username2"],
  "unfollowed_accounts": [
    {"username": "@username1", "timestamp": "ISO-8601"}
  ]
}
```

**Corrupted state recovery**: If JSON is invalid, creates `.backup` and starts fresh with safe defaults.

## Logging

All output goes to both console and `tiktok_unfollower.log`:
- **Rotating logs**: Max 5MB per file, keeps 3 backups (`.log.1`, `.log.2`, `.log.3`)
- **Timestamps**: File logs include full timestamps for debugging
- **Console output**: Clean format without timestamps for readability

Check logs for detailed history of script runs, errors, and debugging information.

## CSV Export

Invalid accounts are automatically exported to `invalid_accounts.csv`:
- **Append mode**: Each run adds new accounts to the file
- **Columns**: Timestamp, Username, Detection Reason
- **Detection reasons**: "Banned account", "Account not found", "Invalid username format", etc.
- **Use case**: Record keeping, manual review, or importing into other tools

## Session Persistence

Browser session is saved to `session.json` after successful login:
- **Benefits**: Avoids logging in every time the script runs
- **Cookies & storage**: Playwright's `storage_state` saves cookies and local storage
- **MFA advantage**: After first MFA completion, subsequent runs may not require it
- **Control**: Set `SAVE_SESSION=false` to disable (forces fresh login each time)
- **Troubleshooting**: Delete `session.json` if you encounter login issues

The session file is loaded in `setup_browser()` if it exists, and saved in `save_session_state()` after successful login.

## Performance Optimization: Skip Processed Accounts

The scanner skips accounts already in `processed_accounts` list:
- **Faster scans**: On subsequent runs, only visits profiles of new/unscanned accounts
- **Efficiency**: Critical for profile-based verification (avoids re-visiting profiles)
- **Logging**: Shows "already processed (skipped)" for first 10 accounts
- **Statistics**: Reports total skipped count at end of scan

**Important**: With profile-based verification, each account check requires:
- Navigate to profile (~3 seconds)
- Check for videos/error messages, handle Refresh button if needed
- Delay before next check (default: 30 seconds with ±25% randomization)

**Timing examples:**
- 10 accounts: ~5 minutes
- 50 accounts: ~25 minutes
- 100 accounts: ~50 minutes

**Bot Detection Prevention:**
- `PROFILE_CHECK_DELAY` adds delay between profile visits (default: 30s)
- Randomization (±25%) makes timing more human-like
- If TikTok shows Refresh buttons, increase this delay to 45-60 seconds

Use `MAX_FOLLOWERS_TO_REVIEW` for faster testing with smaller batches.

## Important Selectors

TikTok's UI relies on dynamically generated class names and `data-e2e` attributes. The script uses multiple selector fallbacks:

- **Following modal**: `[role="dialog"][data-e2e="follow-info-popup"]`
- **Follower list items**: Modal's `li` elements or `[class*="DivUserContainer"]`
- **Username element**: `[class*="PUniqueId"]` or `[data-e2e="following-username"]`
- **Unfollow button**: `button[data-e2e="follow-button"]` with text "Following"
- **Messages menu** (login indicator): `text=Messages`, `[href*="/messages"]`
- **Profile icon**: `[data-e2e="profile-icon"]`

## Error Handling Patterns

The codebase uses extensive error handling:
1. **Configuration validation** - Invalid values fall back to defaults with warnings
2. **State file I/O** - Corrupted JSON triggers backup and fresh start
3. **DOM queries** - Multiple selector fallbacks, manual intervention prompts
4. **Resource cleanup** - Try/except in `cleanup()` to ensure all resources close
5. **Keyboard interrupt** - Catches Ctrl+C, saves progress, exits gracefully
6. **Stale elements** - Re-queries elements by index instead of storing references

## Rate Limiting Strategy

Three-level approach:
1. **Session limit**: Only process `BATCH_SIZE` accounts per run
2. **Action delay**: Wait `ACTION_DELAY` seconds between each unfollow click
3. **Run frequency**: Enforce `UNFOLLOW_DELAY` between script executions via `should_run()`

## MFA/2FA Support

Human-in-the-loop authentication:
1. Script fills credentials and clicks login
2. Waits for "Messages" menu to appear (login indicator)
3. If timeout occurs, prompts user to complete 2FA manually
4. User presses Enter when done, script continues

## Known Risks

- **Account bans**: Automation may violate TikTok ToS
- **UI breakage**: TikTok UI changes require selector updates
- **False positives**: Conservative detection may miss some invalid accounts
- **False negatives**: Pattern matching could incorrectly flag valid accounts (less likely)

## Testing Approach

When modifying this code:
1. Always test with `DRY_RUN=true` first
2. Start with `BATCH_SIZE=1` for testing
3. Use `MAX_FOLLOWERS_TO_REVIEW=50` or `100` to speed up testing (avoids loading all followers)
4. Monitor browser window (keep `HEADLESS=false`)
5. Check `state.json` after each run
6. Test with non-critical account first

## Debugging Tips

- **Login failures**: Check if "Messages" appears in left sidebar after login. Delete `session.json` to force fresh login.
- **Modal not opening**: Verify following count is clickable on profile
- **No followers loading**: Check modal's scroll container in DevTools
- **Detection issues**:
  - Review first 10 accounts (script shows detailed status with reasons)
  - Check `invalid_accounts.csv` for detection patterns
  - Review `tiktok_unfollower.log` for full details
- **Stale elements**: Script already handles this by re-querying by index
- **Performance problems**:
  - Use `MAX_FOLLOWERS_TO_REVIEW` to limit loading during testing
  - Check log file size (rotates at 5MB)
  - Review processed_accounts count in `state.json`
- **Session issues**: Delete `session.json` and `state.json` to reset completely

## Generated Files

The script creates several files (all git-ignored):
- **`state.json`** - Tracks last run time, processed accounts, unfollowed accounts
- **`session.json`** - Saved browser session (cookies, local storage) for faster login
- **`tiktok_unfollower.log`** - Main log file with full details and timestamps
- **`tiktok_unfollower.log.1`, `.log.2`, `.log.3`** - Rotated log backups
- **`invalid_accounts.csv`** - Export of all detected invalid accounts with timestamps and reasons
- **`state.json.backup`** - Automatic backup created if state file becomes corrupted

Safe to delete any of these files to reset (except mid-run for state.json).

## Future Maintenance

If TikTok updates their UI, focus on:
1. Modal selector: `[role="dialog"][data-e2e="follow-info-popup"]`
2. Follower list container: Scrollable div inside modal
3. Follower items: `li` elements or user container divs
4. Username selector: Class containing "PUniqueId" or data-e2e attributes
5. Unfollow button: `data-e2e="follow-button"` with "Following" text
