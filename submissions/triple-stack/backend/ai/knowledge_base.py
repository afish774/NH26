# 25 IT FAQ entries — your RAG source of truth
KNOWLEDGE_BASE = [
    {
        "id": "kb_001",
        "question": "How do I reset my password?",
        "answer": "Go to the company login portal and click 'Forgot Password'. Enter your work email and you'll receive a reset link within 2 minutes. If the email doesn't arrive, check your spam folder or contact IT helpdesk.",
        "category": "access"
    },
    {
        "id": "kb_002",
        "question": "VPN not connecting or VPN login failed",
        "answer": "1. Ensure you're using Cisco AnyConnect or the approved VPN client. 2. Check your internet connection. 3. Use your employee ID + password (not email). 4. If MFA prompt appears, approve it on your authenticator app. 5. If still failing, restart the VPN client and try again.",
        "category": "network"
    },
    {
        "id": "kb_003",
        "question": "How to connect to office WiFi?",
        "answer": "Select 'CorpNet-Secure' from available WiFi networks. Enter your employee credentials (same as your laptop login). For guest WiFi use 'CorpGuest' with password 'Welcome@Office'. Contact IT if you see 'Authentication Failed'.",
        "category": "network"
    },
    {
        "id": "kb_004",
        "question": "Printer not working or printer offline",
        "answer": "1. Check the printer is powered on and paper is loaded. 2. On Windows: Go to Settings > Devices > Printers > right-click your printer > 'See what's printing' > Cancel all jobs. 3. Restart the print spooler: Run 'services.msc', find 'Print Spooler', restart it. 4. Re-add the printer if needed.",
        "category": "hardware"
    },
    {
        "id": "kb_005",
        "question": "How to install software or request application access?",
        "answer": "Standard software (Office, Zoom, Teams) can be installed via the Company Software Center on your desktop. For licensed software, submit a request through the IT portal with your manager's approval. Installation takes 1-2 business days.",
        "category": "software"
    },
    {
        "id": "kb_006",
        "question": "Laptop is slow or running sluggishly",
        "answer": "1. Restart your laptop — clears memory. 2. Check Task Manager (Ctrl+Shift+Esc) for high CPU/RAM processes. 3. Run Windows Update and restart. 4. Clear browser cache. 5. Ensure at least 10GB free disk space. If problem persists after these steps, raise a ticket for hardware check.",
        "category": "hardware"
    },
    {
        "id": "kb_007",
        "question": "How to access Microsoft Teams or Teams not loading?",
        "answer": "1. Clear Teams cache: Close Teams, navigate to %appdata%/Microsoft/Teams, delete the cache folder, reopen Teams. 2. Ensure you're signed in with your work email. 3. Try the web version at teams.microsoft.com as a workaround while the desktop app is fixed.",
        "category": "software"
    },
    {
        "id": "kb_008",
        "question": "Email not sending or Outlook not working",
        "answer": "1. Check your internet connection. 2. In Outlook, look for 'Disconnected' or 'Offline' in the status bar — click it to reconnect. 3. Remove and re-add your email account: File > Account Settings. 4. Try Outlook Web Access (mail.office365.com) as a fallback.",
        "category": "software"
    },
    {
        "id": "kb_009",
        "question": "How to request access to a shared drive or folder?",
        "answer": "Submit a shared drive access request via the IT portal. Include: 1) Your employee ID, 2) The exact drive/folder path, 3) Your manager's email for approval. Access is provisioned within 4 business hours after manager approval.",
        "category": "access"
    },
    {
        "id": "kb_010",
        "question": "Computer won't turn on or won't boot",
        "answer": "1. Check power cable is firmly connected. 2. Try a different power outlet. 3. Hold power button 10 seconds to force shutdown, then restart. 4. If you see a blue screen (BSOD), note the error code and raise an urgent hardware ticket immediately.",
        "category": "hardware"
    },
    {
        "id": "kb_011",
        "question": "How to set up two-factor authentication or MFA?",
        "answer": "Download Microsoft Authenticator on your phone. Go to aka.ms/mfasetup and sign in with your work account. Click 'Add account' in the app and scan the QR code shown on screen. You'll now get MFA prompts for all logins.",
        "category": "access"
    },
    {
        "id": "kb_012",
        "question": "Zoom not working or Zoom video/audio issues",
        "answer": "1. Check your camera and microphone are not blocked by another app. 2. In Zoom settings, manually select your camera and microphone. 3. Update Zoom to the latest version. 4. Test at zoom.us/test. 5. For 'waiting room' issues, ensure the host has started the meeting.",
        "category": "software"
    },
    {
        "id": "kb_013",
        "question": "How to map a network drive?",
        "answer": "On Windows: Open File Explorer > This PC > Map network drive. Enter the server path (e.g. \\\\fileserver\\shared). Check 'Reconnect at sign-in'. Use your domain credentials. Contact IT for the exact server path for your department.",
        "category": "network"
    },
    {
        "id": "kb_014",
        "question": "Screen not displaying or monitor issues",
        "answer": "1. Check cable connections at both the monitor and computer. 2. Press Windows+P to cycle display modes (PC screen only, Duplicate, Extend, Second screen only). 3. Right-click desktop > Display Settings to detect and arrange monitors. 4. Try a different cable or port.",
        "category": "hardware"
    },
    {
        "id": "kb_015",
        "question": "How to clear browser cache or browser running slow?",
        "answer": "Chrome: Ctrl+Shift+Delete > Select 'All time' > Check Cached images and Cookies > Clear data. Edge: Same shortcut. Firefox: Same shortcut. After clearing, restart the browser. This fixes most website loading and login issues.",
        "category": "software"
    },
    {
        "id": "kb_016",
        "question": "How to request a new laptop or hardware replacement?",
        "answer": "Submit a hardware request through the IT portal with justification. New laptops require department head approval. Replacement (broken/end-of-life) requires IT assessment first. Standard provisioning is 3-5 business days.",
        "category": "hardware"
    },
    {
        "id": "kb_017",
        "question": "How to use the company VoIP phone system?",
        "answer": "Your desk phone extension is your employee ID last 4 digits. For external calls, dial 9 first. For international, dial 9+country code. Voicemail PIN is sent to your email on first setup. Download the softphone app for mobile/remote use.",
        "category": "network"
    },
    {
        "id": "kb_018",
        "question": "OneDrive sync issues or files not syncing",
        "answer": "1. Click the OneDrive cloud icon in the system tray. 2. Look for sync errors (red X). 3. Sign out and back in to OneDrive. 4. Ensure the file path is under 260 characters. 5. Files with special characters in names can cause sync failures — rename them.",
        "category": "software"
    },
    {
        "id": "kb_019",
        "question": "How to update Windows or Mac OS?",
        "answer": "Windows: Settings > Windows Update > Check for updates. Mac: System Preferences > Software Update. Always save your work before updating. Updates are mandatory for security compliance. If updates fail, run Windows Update Troubleshooter or contact IT.",
        "category": "software"
    },
    {
        "id": "kb_020",
        "question": "Webcam not detected or camera not working",
        "answer": "1. Check Device Manager for camera (Windows: right-click Start > Device Manager). 2. Ensure no privacy slider is covering the lens. 3. In Windows Settings > Privacy > Camera — ensure app access is allowed. 4. Uninstall/reinstall the camera driver. 5. Test in another app like Camera app.",
        "category": "hardware"
    },
    {
        "id": "kb_021",
        "question": "How to access the company intranet or internal portals?",
        "answer": "The company intranet is accessible at intranet.company.com. You must be connected to the office WiFi or VPN to access it. Use your employee ID and password. Bookmark the URL for quick access.",
        "category": "access"
    },
    {
        "id": "kb_022",
        "question": "USB device not recognized or external drive not working",
        "answer": "1. Try a different USB port. 2. Safely eject and reconnect. 3. Check Disk Management (diskpart) to see if drive is detected but not assigned a letter. 4. Update USB drivers via Device Manager. 5. Try on another computer to isolate if hardware issue.",
        "category": "hardware"
    },
    {
        "id": "kb_023",
        "question": "How to set up email signature in Outlook?",
        "answer": "Outlook: File > Options > Mail > Signatures. Create new signature, paste the company template (available on intranet). Set it as default for new messages and replies. HTML signatures support images — do not alter the company branding.",
        "category": "software"
    },
    {
        "id": "kb_024",
        "question": "Remote desktop or RDP connection failed",
        "answer": "1. Ensure target machine is powered on and connected to network. 2. Verify you have RDP access rights (request via IT portal if not). 3. Check Windows Firewall is not blocking port 3389. 4. Use the full computer name (from System > Computer Name) not IP for stable connection.",
        "category": "network"
    },
    {
        "id": "kb_025",
        "question": "How to report a security incident or suspicious email?",
        "answer": "For phishing emails: Do NOT click any links. Forward the email to security@company.com and delete it. For security incidents (virus, unauthorized access, data breach): Call the Security Hotline immediately: 1800-SEC-HELP. Do not attempt to handle it yourself.",
        "category": "access"
    }
]
