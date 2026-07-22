#!/usr/bin/env python3
"""
Hermes Discord Bridge v5.0 — Multi-Agent Cross-Channel Orchestration
==============================================================
User only talks in #pm. PM Agent orchestrates SA, Coder, QA, Marketing.
Agents communicate across channels via @mention syntax.
"""
import os, sys, asyncio, json, logging, subprocess, re, yaml, time
from pathlib import Path

# ── Plane.so SDLC Integration ────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
import plane_api
import task_map as tkm
# ──────────────────────────────────────────────────────────────────────

TOKEN = open('/home/dennis/.hermes/.env').read().split('DISCORD_BOT_TOKEN=')[1].split('\n')[0].strip()
DISCORD_API = "https://discord.com/api/v10"
BRIDGE_DIR = Path('/home/dennis/.hermes/discord-bridge')
BRIDGE_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(BRIDGE_DIR / 'bridge.log', mode='a'), logging.StreamHandler()]
)

CONFIG_PATH = Path(os.path.expanduser('~/.hermes/config.yaml'))
with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

discord_cfg = CONFIG.get('discord', {})
CHANNEL_PROMPTS = discord_cfg.get('channel_prompts', {})
FREE_CHANNELS_STR = discord_cfg.get('free_response_channels', '')
FREE_CHANNELS = set(c.strip() for c in FREE_CHANNELS_STR.split(',') if c.strip())

# ── Channel registry ──────────────────────────────────────────────
# Maps channel name → ID for agent-to-agent forwarding
CHANNEL_NAMES = {
    '1528310140564934708': '#pm',
    '1528310312317751376': '#sa',
    '1528310344164835389': '#coder',
    '1528310424536354866': '#qa',
    '1528310499773648968': '#marketing',
    '1528336812177883167': '#summary',
}
CHANNEL_BY_NAME = {v: k for k, v in CHANNEL_NAMES.items()}

# Agent cross-channel destinations (who can talk to whom)
# Format: source_channel_name → [target_channel_names]
AGENT_ROUTES = {
    '#pm':        ['#sa', '#marketing'],       # PM → SA, Marketing
    '#sa':        ['#coder', '#qa'],            # SA → Coder, QA
    '#coder':     ['#qa', '#sa'],               # Coder → QA, SA
    '#qa':        ['#sa', '#coder'],            # QA → SA, Coder
    '#marketing': ['#pm'],                      # Marketing → PM
}

# ── Track forwarded messages to prevent loops ─────────────────────
FORWARD_LOG = {}       # src_msg_id → [target_channel_ids]
FORWARD_LOG_MAX = 500

import aiohttp
import discord
from discord.ext import commands

intents = discord.Intents.none()
intents.guilds = True
intents.guild_messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Track processed message IDs
PROCESSED_IDS = set()
PROCESSED_MAX = 300

async def discord_api(method, endpoint, payload=None):
    url = f"{DISCORD_API}{endpoint}"
    headers = {"Authorization": f"Bot {TOKEN}"}
    if payload:
        headers["Content-Type"] = "application/json"
    async with aiohttp.ClientSession() as sess:
        async with sess.request(method, url, headers=headers, json=payload) as r:
            status = r.status
            if status not in (200, 201, 204):
                err = await r.text()
                logging.error(f"Discord API {method} {endpoint}: {status} {err[:200]}")
                return None
            if status == 204:
                return True
            return await r.json()

async def plane_login():
    """Authenticate with Plane.so and store session cookie for API calls."""
    import aiohttp
    base = plane_api.PLANE_BASE_URL
    email = "admin@plane.com"
    password = "PlaneAdmin123!"
    try:
        # Get CSRF token
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"{base}/auth/get-csrf-token/", headers={"Referer": f"{base}/"}) as r:
                data = await r.json()
                csrf = data.get("csrf_token", "")
                raw_cookies = r.headers.getall("Set-Cookie", [])
        
        # Extract csrftoken cookie
        csrf_cookie = None
        for c in raw_cookies:
            if c.startswith("csrftoken="):
                csrf_cookie = c.split(";")[0]
        
        # Login
        cookies = {c.split("=")[0].strip(): c.split("=")[1].split(";")[0].strip()
                   for c in raw_cookies if "=" in c}
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        
        async with aiohttp.ClientSession() as sess:
            async with sess.post(
                f"{base}/auth/sign-in/",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-CSRFToken": csrf,
                    "Referer": f"{base}/",
                    "Cookie": cookie_str,
                },
                data=f"email={email}&password={password}",
                allow_redirects=False,
            ) as r:
                all_cookies = r.headers.getall("Set-Cookie", [])
                session_parts = [c.split(";")[0] for c in all_cookies if "session-id" in c or "csrftoken" in c]
                final_cookie = "; ".join(session_parts)
                
                if "session-id" in final_cookie:
                    plane_api.init(final_cookie)
                    logging.info("✅ Plane.so login successful — session cookie acquired")
                    return True
                else:
                    logging.error(f"❌ Plane.so login failed — no session cookie in response")
                    return False
    except Exception as e:
        logging.error(f"❌ Plane.so login error: {e}")
        return False

async def send_message(channel_id, content, reply_to=None):
    payload = {"content": str(content)[:1900]}
    if reply_to:
        payload["message_reference"] = {"message_id": reply_to}
    result = await discord_api("POST", f"/channels/{channel_id}/messages", payload)
    if result and "id" in result:
        return result["id"]
    return None

async def edit_message(channel_id, message_id, content):
    payload = {"content": str(content)[:1900]}
    result = await discord_api("PATCH", f"/channels/{channel_id}/messages/{message_id}", payload)
    return result is not None

def get_agent_prompt(channel_id):
    return CHANNEL_PROMPTS.get(str(channel_id), '')

async def forward_to_channel(from_channel_id, target_channel_id, content, source_msg_id, depth=0):
    """Forward a message from one agent channel to another."""
    # Prevent re-forwarding the same source to the same target
    if source_msg_id in FORWARD_LOG and target_channel_id in FORWARD_LOG[source_msg_id]:
        return
    FORWARD_LOG.setdefault(source_msg_id, set()).add(target_channel_id)
    if len(FORWARD_LOG) > FORWARD_LOG_MAX:
        FORWARD_LOG.clear()
    
    from_name = CHANNEL_NAMES.get(str(from_channel_id), f"channel:{from_channel_id}")
    to_name = CHANNEL_NAMES.get(str(target_channel_id), f"channel:{target_channel_id}")
    
    # Forward with a "From:" prefix so agents know it's cross-channel
    # Include depth for loop prevention
    next_depth = depth + 1
    prefixed = f"**[↪ {from_name} → {to_name}]** (depth:{next_depth})\n{content}"
    
    msg_id = await send_message(target_channel_id, prefixed[:1900])
    if msg_id:
        logging.info(f"↪ Forwarded from {from_name} to {to_name}: {content[:60]}")
    return msg_id

def parse_cross_channel_messages(content, source_channel_id):
    """Parse agent response for cross-channel @mentions and return list of (target_channel_id, message).
    Format: @channel_name: message text (at start of line)
    """
    source_channel_name = CHANNEL_NAMES.get(str(source_channel_id))
    if not source_channel_name:
        return []
    
    allowed_targets = AGENT_ROUTES.get(source_channel_name, [])
    if not allowed_targets:
        return []
    
    results = []
    for line in content.split('\n'):
        line = line.strip()
        for target_name in allowed_targets:
            # Match @sa:, @coder:, @qa:, @pm:, @marketing: at start of line
            pattern = rf'^@{target_name[1:]}:?\s*(.*)'  # strip # from channel name
            m = re.match(pattern, line, re.IGNORECASE)
            if m and m.group(1).strip():
                target_id = CHANNEL_BY_NAME.get(target_name)
                if target_id and target_id != source_channel_id:
                    results.append((target_id, m.group(1).strip()))
                    break  # Only match one target per line
    
    return results

async def process_message(msg):
    """Route message to correct agent and handle cross-channel forwarding."""
    logging.info(f"⚡ on_message triggered: author={msg.author} type={msg.type} content_preview={msg.content[:80]}")
    if msg.type not in (discord.MessageType.default, discord.MessageType.reply):
        logging.info(f"  ↳ Skipping: msg.type={msg.type} not in (default, reply)")
        return
    
    # ── Handle cross-channel forwards (bot's own messages) ──
    is_forward = False
    forward_depth = 0
    raw_content = msg.content
    
    if msg.author == bot.user:
        # Only process if it's a cross-channel forward (starts with **[↪...]**)
        if raw_content.startswith('**[↪'):
            is_forward = True
            # Extract forward depth if present
            depth_match = re.search(r'depth:(\d+)', raw_content)
            forward_depth = int(depth_match.group(1)) if depth_match else 0
            if forward_depth >= 5:
                logging.warning(f"Forward depth limit reached ({forward_depth}), skipping")
                return
        else:
            return  # Skip all other bot messages
    
    # Deduplicate
    if msg.id in PROCESSED_IDS:
        return
    PROCESSED_IDS.add(msg.id)
    if len(PROCESSED_IDS) > PROCESSED_MAX:
        PROCESSED_IDS.clear()
    
    channel_id = str(msg.channel.id)
    channel_name = CHANNEL_NAMES.get(channel_id, f'channel:{channel_id}')
    
    # ── Extract real content (strip forward prefix) ──
    if is_forward:
        # Format: **[↪ #pm → #sa]**\ncontent
        lines = raw_content.split('\n', 1)
        if len(lines) > 1:
            content = lines[1].strip()
        else:
            content = ""
        logging.info(f"↪ [{channel_name}] Forward received: {content[:80]}")
    else:
        content = raw_content
    
    # Check if we should respond
    bot_mentioned = bot.user in msg.mentions
    is_free = channel_id in FREE_CHANNELS
    has_prompt = channel_id in CHANNEL_PROMPTS
    
    should_respond = False
    if has_prompt or is_free or is_forward:
        should_respond = True
    elif bot_mentioned:
        should_respond = True
    # #summary is read-only
    if channel_id == '1528336812177883167':
        should_respond = False
    
    if not should_respond:
        return
    
    system_prompt = get_agent_prompt(channel_id)
    
    # Strip bot mention from user messages only
    if not is_forward and bot_mentioned:
        content = re.sub(r'<@!?(\d+)>', '', content).strip()
    if not content:
        return
    
    # ── Fetch referenced message for reply context ──
    quoted_context = ""
    if msg.reference and msg.reference.message_id:
        try:
            ref_msg_id = str(msg.reference.message_id)
            ref_data = await discord_api("GET", f"/channels/{channel_id}/messages/{ref_msg_id}")
            if ref_data and isinstance(ref_data, dict):
                ref_author = ref_data.get('author', {}).get('username', 'Unknown')
                ref_content = ref_data.get('content', '')[:500]
                if ref_content:
                    quoted_context = f"\n\n[REPLYING TO — {ref_author} said:]\n{ref_content}\n"
                    logging.info(f"  ↳ Reply to: {ref_content[:60]}")
        except Exception as e:
            logging.warning(f"  ↳ Could not fetch referenced message: {e}")
    
    logging.info(f"→ [{channel_name}] {msg.author}: {content[:120]}")
    
    # Send typing indicator
    await discord_api("POST", f"/channels/{channel_id}/typing")
    
    # Send immediate acknowledgment
    ack_id = await send_message(channel_id, "🔄 **Processing...**", reply_to=msg.id)
    if not ack_id:
        logging.error(f"Failed to send ack in {channel_name}")
        return
    
    # Build prompt with system context + cross-channel awareness
    if system_prompt:
        # Add routing instructions for cross-channel communication
        routing_guide = ""
        if channel_id in CHANNEL_BY_NAME:
            ch_name = CHANNEL_BY_NAME.get(channel_id, "#pm")
            allowed_targets = AGENT_ROUTES.get(ch_name, [])
            if allowed_targets:
                targets_str = ", ".join(allowed_targets)
                routing_guide = f"\n\nCROSS-CHANNEL RULES:\n- To talk to another agent, START a line with @channel_name: message\n- You can talk to: {targets_str}\n- Example: @sa: Please produce a spec for TASK-001\n- The bridge will forward your message to that channel automatically."
        
        full_prompt = f"[SYSTEM PROMPT]\n{system_prompt}{routing_guide}{quoted_context}\n\n[MESSAGE]\n{content}"
    else:
        full_prompt = f"{quoted_context}\n\n{content}" if quoted_context else content
    
    # ── Plane.so SDLC Integration: Create/Lookup Ticket ────────────
    ticket_url = ""
    ticket_ref = ""
    plane_issue_id = None
    
    if channel_id == CHANNEL_BY_NAME.get('#pm') or channel_id == CHANNEL_BY_NAME.get('#sa'):
        existing_task = tkm.guess_task_reference(content)
        is_new_task = re.search(r'(create|new|assign)\s+(a\s+)?(task|issue|ticket)', content, re.IGNORECASE)
        
        if existing_task and tkm.task_exists(existing_task):
            # Existing task — just reference it
            task_info = tkm.get_task(existing_task)
            if task_info:
                ticket_url = task_info["url"]
                ticket_ref = f"{task_info.get('name', existing_task)}"
                plane_issue_id = task_info["plane_issue_id"]
                logging.info(f"🔗 Referenced existing {existing_task} → {ticket_url}")
        elif is_new_task or not existing_task:
            # Create a new Plane issue
            task_num = tkm.next_task_number()
            task_id = f"TASK-{task_num:03d}"
            
            # Extract a good name from the message
            first_line = content.split('\n')[0][:80]
            issue_name = f"{task_id}: {first_line}"
            
            issue_id, seq_id, url = await plane_api.create_issue(
                name=issue_name,
                description=content[:2000],
                priority="medium",
            )
            
            if issue_id:
                tkm.set_task(task_id, issue_id, seq_id, url, name=issue_name)
                ticket_url = url
                ticket_ref = f"{task_id}"
                plane_issue_id = issue_id
                logging.info(f"🎫 Created {task_id} → {url}")
    
    # Inject ticket context into the prompt
    ticket_context = ""
    if ticket_url:
        ticket_context = f"\n\n[TICKET REFERENCE]\nTicket: {ticket_ref}\nURL: {ticket_url}\nInclude this URL in your response when referencing this task.\n"
        full_prompt += ticket_context
    
    session_name = f"discord-{channel_id}"
    
    try:
        proc = await asyncio.create_subprocess_exec(
            'hermes', '-z', full_prompt,
            '--resume', session_name,
            '--safe-mode', '--yolo',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        
        response = stdout.decode().strip() if stdout else ""
        
        if response:
            # Clean up TUI artifacts
            lines = response.split('\n')
            clean_lines = []
            for l in lines:
                stripped = l.strip()
                if not stripped:
                    clean_lines.append('')
                elif any(stripped.startswith(c) for c in ('╭', '╰', '│', '─', '⚠', '✦', '●', '┃', '┣', '┗', '┏', '┓', '┛', '┳', '┻', '┫', '━')):
                    continue
                elif re.match(r'^[\d:.,\s\-]+$', stripped):
                    continue
                else:
                    clean_lines.append(stripped)
            
            clean = '\n'.join(clean_lines).strip()
            if not clean or len(clean) < 5:
                meaningful = [l for l in lines if len(l.strip()) > 10 and not l.strip().startswith('Hermes')]
                clean = meaningful[-1].strip() if meaningful else response[:1900]
            
            # ── Step 1: Forward cross-channel messages ──
            forwards = parse_cross_channel_messages(clean, channel_id)
            current_depth = forward_depth if is_forward else 0
            for target_id, fwd_msg in forwards:
                await forward_to_channel(channel_id, target_id, fwd_msg, msg.id, current_depth)
            
            # ── Step 2: Reply in the original channel ──
            # Remove cross-channel lines from the reply to avoid clutter
            display_lines = []
            for line in clean.split('\n'):
                is_fwd = False
                for target_name in AGENT_ROUTES.get(CHANNEL_NAMES.get(str(channel_id), ''), []):
                    if re.match(rf'^@{target_name[1:]}:?\s', line.strip(), re.IGNORECASE):
                        is_fwd = True
                        break
                if not is_fwd:
                    display_lines.append(line)
            
            display = '\n'.join(display_lines).strip()
            
            if display and len(display) > 5:
                # ── Plane.so SDLC: Update issue status ────────────
                status_text = tkm.find_status_in_text(display)
                if status_text and plane_issue_id:
                    await plane_api.update_by_status_keyword(plane_issue_id, status_text)
                
                # Append ticket URL if we have one
                if ticket_url:
                    if not display.endswith('\n'):
                        display += '\n'
                    display += f"\n🔗 **Ticket:** {ticket_url}"
                
                # If there are forwards, add a note
                if forwards:
                    target_names = ', '.join([CHANNEL_NAMES.get(str(t), '?') for t, _ in forwards])
                    display += f"\n\n_↪ Forwarded to {target_names}_"
                
                await edit_message(channel_id, ack_id, display[:1900])
                logging.info(f"✓ [{channel_name}] Response: {display[:80]}")
            else:
                # Response was all cross-channel forwards
                if forwards:
                    await edit_message(channel_id, ack_id, f"✅ Message forwarded to agents ✅")
                else:
                    await edit_message(channel_id, ack_id, "✅ Done")
                    logging.warning(f"[{channel_name}] Echo/empty: {response[:100]}")
        else:
            err = stderr.decode().strip() if stderr else ""
            logging.warning(f"[{channel_name}] Empty response. Stderr: {err[:200]}")
            await edit_message(channel_id, ack_id, "⚠️ Empty response. Try again?")
            
    except asyncio.TimeoutError:
        logging.error(f"[{channel_name}] Timed out")
        await edit_message(channel_id, ack_id, "⏱️ Timed out (600s). Please try a shorter query.")
    except Exception as e:
        logging.error(f"[{channel_name}] Error: {e}")
        await edit_message(channel_id, ack_id, f"⚠️ Error: {str(e)[:150]}")

@bot.event
async def on_ready():
    logging.info(f"✓ CONNECTED AS {bot.user} ({bot.user.id})")
    logging.info(f"  Guilds: {len(bot.guilds)}")
    for g in bot.guilds:
        logging.info(f"  - {g.name} ({g.id})")
    logging.info(f"  Agents loaded: {len(CHANNEL_PROMPTS)}")
    logging.info(f"  Routes:")
    for src, targets in AGENT_ROUTES.items():
        logging.info(f"    {src} → {', '.join(targets)}")

@bot.event
async def on_message(msg):
    await process_message(msg)

@bot.event
async def on_error(event, *args):
    import traceback
    logging.error(f"Event error {event}: {traceback.format_exc()}")

async def main():
    logging.info("=" * 50)
    logging.info("HERMES DISCORD BRIDGE v6.0 — MULTI-AGENT + PLANE SDLC")
    logging.info("=" * 50)
    logging.info(f"Loaded {len(CHANNEL_PROMPTS)} agent prompts")
    for cid, prompt in CHANNEL_PROMPTS.items():
        first_line = prompt.strip().split('\n')[0][:60]
        name = CHANNEL_NAMES.get(cid, cid)
        logging.info(f"  {name:30s} → {first_line}")
    logging.info(f"\nCross-channel routes:")
    for src, targets in AGENT_ROUTES.items():
        logging.info(f"  {src} → {', '.join(targets)}")
    
    # ── Initialize Plane.so API connection ──
    logged_in = await plane_login()
    if logged_in:
        logging.info("✓ Plane.so SDLC integration active")
    else:
        logging.warning("⚠ Plane.so login failed — tickets will not be created")
    
    logging.info("logging in...")
    await bot.start(TOKEN)

if __name__ == '__main__':
    asyncio.run(main())
