#!/usr/bin/env python3
"""
Plane.so API client for the Discord Bridge.
Handles issue (ticket) creation, status updates, and URL generation.
"""
import os, json, logging, asyncio, time
from urllib.parse import urljoin

logger = logging.getLogger('plane_api')

# ── Plane.so Instance Configuration ──────────────────────────────────
PLANE_BASE_URL = os.environ.get('PLANE_BASE_URL', 'http://10.242.219.145:3400')
WORKSPACE_SLUG = os.environ.get('PLANE_WORKSPACE', 'omnireach')
PROJECT_ID = os.environ.get('PLANE_PROJECT_ID', '15b9997e-a1ae-47d0-a3d7-ece8cbe96573')

# State IDs for the SDLC project
STATE_BACKLOG = '793ec185-50ef-43cd-ad59-2dc296cf3406'
STATE_TODO = '463176e1-2376-41c1-ba98-ba3c63906e87'
STATE_IN_PROGRESS = 'a881a006-0ded-4a61-b850-511e7449cf32'
STATE_IN_REVIEW = '7df3cb51-ab29-498f-bc99-ec3f58da53d5'   # Code submitted for review
STATE_QA_FAILED = '6d7c17ba-b64b-489a-b551-40b192999a78'    # QA failed - needs rework
STATE_QA_VERIFIED = '6836ec4b-9084-42ff-b5d9-3ff24ac7a09e'  # QA passed
STATE_DONE = '4293aec8-41fb-4cad-81ce-625cfa0a29be'
STATE_CANCELLED = '016df94f-22c8-4918-b067-88167d2c1e87'

# Session cookie for API auth — set by init from bridge
SESSION_COOKIE = None

def init(session_cookie):
    """Initialize the Plane API with the admin session cookie."""
    global SESSION_COOKIE
    SESSION_COOKIE = session_cookie
    logger.info("PlaneAPI initialized with session cookie")

async def api_request(method, path, data=None):
    """Make an API request to Plane.so with cookie auth."""
    import aiohttp
    
    url = urljoin(PLANE_BASE_URL, path)
    headers = {
        "Content-Type": "application/json",
        "Cookie": SESSION_COOKIE or "",
        "Referer": f"{PLANE_BASE_URL}/",
    }
    
    async with aiohttp.ClientSession() as sess:
        async with sess.request(method, url, headers=headers, json=data) as r:
            status = r.status
            if status in (200, 201):
                return await r.json()
            elif status == 204:
                return True
            else:
                body = await r.text()
                logger.error(f"Plane API {method} {path}: {status} {body[:200]}")
                return None

async def create_issue(name, description="", priority="medium", state_id=None):
    """
    Create a new issue (ticket) in Plane.
    Returns (issue_id, sequence_id, url) or (None, None, None) on failure.
    """
    if not state_id:
        state_id = STATE_BACKLOG
    
    payload = {
        "name": name,
        "description_html": f"<p>{description}</p>" if description else "<p></p>",
        "state": state_id,
        "priority": priority,
    }
    
    result = await api_request(
        "POST",
        f"/api/workspaces/{WORKSPACE_SLUG}/projects/{PROJECT_ID}/issues/",
        payload,
    )
    
    if result and "id" in result:
        issue_id = result["id"]
        sequence_id = result.get("sequence_id", 0)
        url = get_issue_url(issue_id)
        logger.info(f"✅ Created Plane issue: {name[:50]} → {url}")
        return issue_id, sequence_id, url
    
    logger.error(f"❌ Failed to create issue: {name[:50]}")
    return None, None, None

async def update_issue_state(issue_id, state_id):
    """Update an issue's state (status). Returns True on success."""
    result = await api_request(
        "PATCH",
        f"/api/workspaces/{WORKSPACE_SLUG}/projects/{PROJECT_ID}/issues/{issue_id}/",
        {"state": state_id},
    )
    if result is not None:
        logger.info(f"✅ Updated issue {issue_id[:8]} to state {state_id[:8]}")
        return True
    logger.error(f"❌ Failed to update issue {issue_id[:8]}")
    return False

async def update_issue(issue_id, **kwargs):
    """Update arbitrary fields on an issue."""
    result = await api_request(
        "PATCH",
        f"/api/workspaces/{WORKSPACE_SLUG}/projects/{PROJECT_ID}/issues/{issue_id}/",
        kwargs,
    )
    return result is not None

def get_issue_url(issue_id):
    """Return the web URL for an issue."""
    return f"{PLANE_BASE_URL}/projects/{PROJECT_ID}/issues/{issue_id}"

# ── Full SDLC Status Map ────────────────────────────────────────────
# Maps status keywords/phrases to Plane.so state IDs.
# Covers the complete agent workflow: PM→SA→Coder→QA→Done
STATUS_MAP = {
    # Backlog
    "backlog": STATE_BACKLOG,
    "idea": STATE_BACKLOG,
    
    # Todo / Unstarted
    "todo": STATE_TODO,
    "to do": STATE_TODO,
    "open": STATE_TODO,
    "ready": STATE_TODO,
    "not started": STATE_TODO,
    
    # In Progress (Coder working)
    "in progress": STATE_IN_PROGRESS,
    "wip": STATE_IN_PROGRESS,
    "working": STATE_IN_PROGRESS,
    "started": STATE_IN_PROGRESS,
    "implementing": STATE_IN_PROGRESS,
    "coding": STATE_IN_PROGRESS,
    
    # In Review (submitted for code review / QA)
    "in review": STATE_IN_REVIEW,
    "review": STATE_IN_REVIEW,
    "needs review": STATE_IN_REVIEW,
    "ready for review": STATE_IN_REVIEW,
    "code review": STATE_IN_REVIEW,
    "submitted": STATE_IN_REVIEW,
    "pending review": STATE_IN_REVIEW,
    "awaiting review": STATE_IN_REVIEW,
    "qa review": STATE_IN_REVIEW,
    "pr submitted": STATE_IN_REVIEW,
    "pull request": STATE_IN_REVIEW,
    
    # QA Failed (rework needed)
    "qa failed": STATE_QA_FAILED,
    "failed qa": STATE_QA_FAILED,
    "rework": STATE_QA_FAILED,
    "needs rework": STATE_QA_FAILED,
    "fix needed": STATE_QA_FAILED,
    "bugs found": STATE_QA_FAILED,
    "rejected": STATE_QA_FAILED,
    "changes requested": STATE_QA_FAILED,
    "qa rejected": STATE_QA_FAILED,
    "not approved": STATE_QA_FAILED,
    
    # QA Verified (passed QA, ready for merge)
    "qa verified": STATE_QA_VERIFIED,
    "passed qa": STATE_QA_VERIFIED,
    "qa passed": STATE_QA_VERIFIED,
    "verified": STATE_QA_VERIFIED,
    "approved": STATE_QA_VERIFIED,
    "qa approved": STATE_QA_VERIFIED,
    "sign off": STATE_QA_VERIFIED,
    "signed off": STATE_QA_VERIFIED,
    "ready to merge": STATE_QA_VERIFIED,
    "ready for deploy": STATE_QA_VERIFIED,
    "ready for production": STATE_QA_VERIFIED,
    
    # Done / Completed
    "done": STATE_DONE,
    "completed": STATE_DONE,
    "finished": STATE_DONE,
    "resolved": STATE_DONE,
    "merged": STATE_DONE,
    "deployed": STATE_DONE,
    "released": STATE_DONE,
    "production": STATE_DONE,
    "closed": STATE_DONE,
    
    # Cancelled / Blocked
    "cancelled": STATE_CANCELLED,
    "canceled": STATE_CANCELLED,
    "blocked": STATE_CANCELLED,
    "wontfix": STATE_CANCELLED,
    "wont fix": STATE_CANCELLED,
    "abandoned": STATE_CANCELLED,
    "duplicate": STATE_CANCELLED,
    "obsolete": STATE_CANCELLED,
}

async def update_by_status_keyword(issue_id, status_text):
    """Parse a status keyword from text and update the issue state."""
    status_lower = status_text.strip().lower()
    state_id = STATUS_MAP.get(status_lower)
    if state_id:
        return await update_issue_state(issue_id, state_id)
    return False
