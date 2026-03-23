"""
Run after server is up: python database/seed.py

Seeds demo tickets and agents for testing.
"""

import requests
import uuid

BASE = "http://localhost:8080/api"

# ─────────────────────────────────────────────────────────────────────────────
# DEMO AGENTS
# ─────────────────────────────────────────────────────────────────────────────

AGENTS = [
    {
        "name": "Sarah Chen",
        "email": "sarah.chen@nexdesk.local",
        "specializations": ["hardware", "network"],
        "max_tickets": 8,
        "is_available": True,
    },
    {
        "name": "Marcus Rodriguez",
        "email": "marcus.r@nexdesk.local",
        "specializations": ["software", "email"],
        "max_tickets": 10,
        "is_available": True,
    },
    {
        "name": "Emily Watson",
        "email": "emily.w@nexdesk.local",
        "specializations": ["security", "access"],
        "max_tickets": 6,
        "is_available": True,
    },
    {
        "name": "James Park",
        "email": "james.p@nexdesk.local",
        "specializations": ["hardware", "software", "network"],
        "max_tickets": 12,
        "is_available": True,
    },
    {
        "name": "Lisa Thompson",
        "email": "lisa.t@nexdesk.local",
        "specializations": ["email", "software"],
        "max_tickets": 8,
        "is_available": False,  # Currently unavailable
    },
]

print("=" * 60)
print("SEEDING DEMO AGENTS")
print("=" * 60)

for agent in AGENTS:
    try:
        r = requests.post(f"{BASE}/agents/", json=agent)
        if r.status_code == 200:
            d = r.json()
            status = "available" if agent["is_available"] else "offline"
            print(
                f"  {agent['name']:<20} [{status}] → {', '.join(agent['specializations'])}"
            )
        else:
            print(f"  {agent['name']:<20} — already exists or error: {r.status_code}")
    except Exception as e:
        print(f"  {agent['name']:<20} — error: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# DEMO TICKETS
# ─────────────────────────────────────────────────────────────────────────────

TICKETS = [
    {
        "title": "Cannot connect to VPN from home",
        "description": "VPN disconnects every 20 minutes while working from home. Using Cisco AnyConnect. Very disruptive for video calls.",
    },
    {
        "title": "URGENT — Laptop screen cracked, client meeting in 2 hours",
        "description": "My laptop screen cracked and I have a client presentation in 2 hours. Need urgent replacement or external monitor immediately.",
    },
    {
        "title": "Outlook stuck on loading profile for 2 days",
        "description": "Outlook has been stuck on the loading screen for 2 days. Cannot access emails at all. Tried restarting multiple times.",
    },
    {
        "title": "Cannot access Finance shared drive",
        "description": "Getting access denied when opening the Finance shared drive. I had access last week. Need it for month-end reports.",
    },
    {
        "title": "Printer on 3rd floor shows offline",
        "description": "The HP LaserJet on 3rd floor shows offline even though it is powered on. Multiple people are affected.",
    },
    {
        "title": "Teams video calls pixelated and dropping",
        "description": "All Teams video calls are very low quality and frequently dropping. Audio is fine. Started happening after Windows update.",
    },
    {
        "title": "Suspicious phishing email received",
        "description": "Received an email from IT-security@company-secure.net asking to verify my password by clicking a link. Did not click. Is this legitimate?",
    },
    {
        "title": "New employee laptop not set up",
        "description": "Joined on Monday and my laptop does not have any company software installed. Cannot access email, Teams, or any tools.",
    },
    {
        "title": "Software license expired for Adobe Acrobat",
        "description": "Getting a license expired popup on Adobe Acrobat every time I open it. Need it for processing contracts urgently.",
    },
    {
        "title": "OneDrive not syncing files since yesterday",
        "description": "OneDrive shows a red X and files from yesterday are not synced. Working on important documents that need to be backed up.",
    },
    {
        "title": "VPN authentication failed after password reset",
        "description": "Reset my password yesterday and now VPN says authentication failed. Cannot work from home.",
    },
    {
        "title": "Laptop extremely slow after Windows update",
        "description": "After Windows update laptop takes 15 minutes to boot and all apps lag heavily. Have a project delivery deadline today.",
    },
]

print("\n" + "=" * 60)
print("SEEDING DEMO TICKETS")
print("=" * 60)

for t in TICKETS:
    try:
        r = requests.post(
            f"{BASE}/tickets/", json={**t, "user_id": f"demo_{uuid.uuid4().hex[:6]}"}
        )
        d = r.json()
        print(
            f"  {t['title'][:42]:<42} → {d.get('priority', '?')}/{d.get('category', '?')}"
        )
    except Exception as e:
        print(f"  {t['title'][:42]} — {e}")

print("\n" + "=" * 60)
print("SEEDING COMPLETE")
print("=" * 60)
print("\nVisit:")
print("  API Docs: http://localhost:8000/docs")
print("  Frontend: http://localhost:3000/dashboard")
