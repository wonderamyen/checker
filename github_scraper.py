import requests
import time
import re
from collections import deque
import os # Import os to access environment variables

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# --- Config ---
# Read from environment variables, with fallbacks to original defaults
# TARGET_SKINS will be a comma-separated string from env, so we split it.
SEED_STEAMID  = os.getenv("SEED_STEAMID", "76561199258852510")
TARGET_SKINS  = [s.strip() for s in os.getenv("TARGET_SKINS", "Printstream,Asiimov,Knife,Gloves").split(',')]
ACCOUNT_LIMIT = int(os.getenv("ACCOUNT_LIMIT", "50"))
MAX_LEVEL     = int(os.getenv("MAX_LEVEL", "15"))
MAX_CS2_HOURS = int(os.getenv("MAX_CS2_HOURS", "1500"))
DELAY_BETWEEN = float(os.getenv("DELAY_BETWEEN", "5.0"))
PAGE_DELAY    = float(os.getenv("PAGE_DELAY", "1.5"))

# --- Telegram ---
# IMPORTANT: These should be set as GitHub Secrets, not hardcoded!
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_PLACEHOLDER")
TG_CHAT_ID   = os.getenv("TG_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID_PLACEHOLDER")
# ----------------


def send_telegram(links):
    """Send profile links to Telegram in batches to respect the 4096 character limit."""
    if not links:
        return
    
    # Only send if token and chat_id are provided (i.e., not default placeholders)
    if TG_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_PLACEHOLDER" or TG_CHAT_ID == "YOUR_TELEGRAM_CHAT_ID_PLACEHOLDER":
        print("Telegram token or chat ID not configured. Skipping Telegram notification.")
        return

    # Calculate max links per batch (each link is ~38 characters)
    # "https://steamcommunity.com/profiles/76561199258852510" = ~38 chars
    # We'll use a conservative estimate of 40 chars per link + newline
    MAX_CHARS = 4096
    CHARS_PER_LINK = 40  # conservative estimate
    MAX_LINKS_PER_BATCH = MAX_CHARS // CHARS_PER_LINK
    
    # Alternatively, you can set a fixed number of links per batch
    # MAX_LINKS_PER_BATCH = 40  # Uncomment this line to use a fixed number
    
    total_batches = (len(links) + MAX_LINKS_PER_BATCH - 1) // MAX_LINKS_PER_BATCH
    
    for batch_num in range(total_batches):
        start_idx = batch_num * MAX_LINKS_PER_BATCH
        end_idx = min(start_idx + MAX_LINKS_PER_BATCH, len(links))
        batch_links = links[start_idx:end_idx]
        
        message = "\n".join(batch_links)
        
        # Double-check we're within the limit
        if len(message) > MAX_CHARS:
            # If still too long, split by character count instead of link count
            # This is a safety fallback
            messages = []
            current_msg = ""
            for link in batch_links:
                if len(current_msg) + len(link) + 1 > MAX_CHARS:  # +1 for newline
                    messages.append(current_msg)
                    current_msg = link
                else:
                    if current_msg:
                        current_msg += "\n" + link
                    else:
                        current_msg = link
            if current_msg:
                messages.append(current_msg)
            
            # Send each message chunk
            for msg in messages:
                try:
                    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
                    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg})
                    print(f"Sent {len(msg.split(chr(10)))} links in chunk.")
                    time.sleep(0.5)  # Small delay between messages to avoid rate limits
                except Exception as e:
                    print(f"Telegram error: {e}")
        else:
            # Send the batch normally
            try:
                url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
                requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message})
                print(f"Sent batch {batch_num + 1}/{total_batches} ({len(batch_links)} links).")
                time.sleep(0.5)  # Small delay between messages to avoid rate limits
            except Exception as e:
                print(f"Telegram error: {e}")


def get_inventory(steamid64):
    items        = []
    last_assetid = None

    while True:
        url = f"https://steamcommunity.com/inventory/{steamid64}/730/2?l=english&count=75"
        if last_assetid:
            url += f"&start_assetid={last_assetid}"

        try:
            response = requests.get(url, headers=HEADERS, timeout=10) # Added timeout
        except requests.exceptions.RequestException as e:
            print(f"  Inventory request failed for {steamid64}: {e}")
            return []

        if response.status_code == 429:
            print("  Rate limited. Waiting 20 seconds...")
            time.sleep(20)
            continue
        elif response.status_code in (400, 403, 401):
            # print(f"  Inventory not accessible for {steamid64} (status {response.status_code}).") # Suppress for cleaner logs
            return []
        elif response.status_code != 200:
            print(f"  Unexpected error for {steamid64}: {response.status_code}")
            return []

        try:
            data         = response.json()
            assets       = data.get("assets", [])
            descriptions = data.get("descriptions", [])
        except ValueError: # Catch JSONDecodeError for non-JSON responses
            print(f"  Failed to decode JSON for inventory of {steamid64}.")
            return []

        desc_lookup = {
            (d["classid"], d["instanceid"]): d
            for d in descriptions
        }

        for asset in assets:
            key  = (asset["classid"], asset["instanceid"])
            desc = desc_lookup.get(key, {})
            items.append({
                "assetid":  asset["assetid"],
                "name":     desc.get("market_hash_name", "Unknown"),
                "type":     desc.get("type", "Unknown"),
                "tradable": desc.get("tradable", 0) == 1,
            })

        if data.get("more_items"):
            if assets: # Ensure assets list is not empty before accessing last element
                last_assetid = assets[-1]["assetid"]
                time.sleep(PAGE_DELAY)
            else: # No assets but more_items is true, might be an issue or end of list
                break
        else:
            break

    return items


def get_friends(steamid64):
    url      = f"https://steamcommunity.com/profiles/{steamid64}/friends"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10) # Added timeout
    except requests.exceptions.RequestException as e:
        print(f"  Friends request failed for {steamid64}: {e}")
        return []

    if response.status_code != 200:
        # print(f"  Could not fetch friends page for {steamid64} (status {response.status_code})") # Suppress for cleaner logs
        return []

    friends = re.findall(r'data-steamid="(\d{17})"', response.text)

    seen, unique = set(), []
    for f in friends:
        if f not in seen and f != steamid64:
            seen.add(f)
            unique.append(f)

    return unique


def get_profile_info(steamid64):
    """Fetch level and CS2 hours from the profile page in a single request.
    Returns (level, hours) where either can be -1 if not found."""
    url      = f"https://steamcommunity.com/profiles/{steamid64}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10) # Added timeout
    except requests.exceptions.RequestException as e:
        print(f"  Profile info request failed for {steamid64}: {e}")
        return -1, -1

    if response.status_code != 200:
        return -1, -1

    html = response.text

    level_match = re.search(r'friendPlayerLevelNum"[^>]*>(\d+)<', html)
    level = int(level_match.group(1)) if level_match else -1

    # structure: app/730 link -> game_info_details div -> "X,XXX hrs on record"
    cs2_match = re.search(
        r'steamcommunity\.com/app/730.{0,500}?game_info_details[^>]*>.{0,200}?([\d,]+\.?\d*)\s+hrs on record',
        html, re.DOTALL
    )
    hours = float(cs2_match.group(1).replace(",", "")) if cs2_match else -1

    return level, hours


def find_matching_skins(items, target_skins):
    targets_lower = [s.lower().strip() for s in target_skins]
    matches = []
    for item in items:
        name_lower = item["name"].lower()
        for target in targets_lower:
            if target in name_lower:
                matches.append(item)
                break
    return matches


def run_scraper():
    print(f"Starting scraper with configuration:")
    print(f"  Seed SteamID: {SEED_STEAMID}")
    print(f"  Target Skins: {TARGET_SKINS}")
    print(f"  Account Limit: {ACCOUNT_LIMIT}")
    print(f"  Max Level: {MAX_LEVEL}")
    print(f"  Max CS2 Hours: {MAX_CS2_HOURS}")
    print(f"  Delay Between Accounts: {DELAY_BETWEEN}s")
    print(f"  Telegram Enabled: {'Yes' if TG_BOT_TOKEN != 'YOUR_TELEGRAM_BOT_TOKEN_PLACEHOLDER' and TG_CHAT_ID != 'YOUR_TELEGRAM_CHAT_ID_PLACEHOLDER' else 'No'}")
    print("-" * 50)

    visited  = set()
    queue    = deque([(SEED_STEAMID, 0)])
    scraped  = 0   # accounts that passed filters and had inventory checked
    all_hits = []

    while queue and scraped < ACCOUNT_LIMIT:
        steamid, depth = queue.popleft()

        if steamid in visited:
            continue
        visited.add(steamid)

        print(f"[{scraped+1}/{ACCOUNT_LIMIT}] Checking {steamid}", end=" ... ")

        level, hours = get_profile_info(steamid)
        
        # Filter Logic
        if level == -1:
            print(f"profile info not found/private, skipping.")
            # Still try to get friends to continue crawling
            friends = get_friends(steamid)
            for friend in [f for f in friends if f not in visited]:
                queue.append((friend, depth + 1))
            time.sleep(DELAY_BETWEEN)
            continue
        
        if level > MAX_LEVEL:
            print(f"skipped (level {level} > {MAX_LEVEL})")
            friends = get_friends(steamid)
            for friend in [f for f in friends if f not in visited]:
                queue.append((friend, depth + 1))
            time.sleep(DELAY_BETWEEN)
            continue

        if hours != -1 and hours > MAX_CS2_HOURS:
            print(f"skipped ({hours}h > {MAX_CS2_HOURS}h)")
            friends = get_friends(steamid)
            for friend in [f for f in friends if f not in visited]:
                queue.append((friend, depth + 1))
            time.sleep(DELAY_BETWEEN)
            continue

        scraped += 1
        items   = get_inventory(steamid)
        matches = find_matching_skins(items, TARGET_SKINS)

        if matches:
            skin_names = ", ".join(m["name"] for m in matches)
            print(f"HIT -> {skin_names}")
            all_hits.append(f"https://steamcommunity.com/profiles/{steamid}")
        else:
            print("no match")

        friends = get_friends(steamid)
        for friend in [f for f in friends if f not in visited]:
            queue.append((friend, depth + 1))

        time.sleep(DELAY_BETWEEN)

    if all_hits:
        print(f"\nSending {len(all_hits)} link(s) to Telegram...")
        send_telegram(all_hits)

    print(f"\nDone. Scraped {scraped} account(s). Hits: {len(all_hits)}")


if __name__ == "__main__":
    run_scraper()
