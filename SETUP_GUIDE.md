# Maa — Setup Guide: Vapi, Email & Google Calendar

---

## 1. VAPI (Outbound Calls to ASHA Worker)

### Get API Keys
1. Go to https://dashboard.vapi.ai → Sign up / Log in
2. Left sidebar → **Organization Settings** → **API Keys**
3. Click **Create API Key** → Copy it
4. Repeat if you want multiple keys for rotation

### Get Phone Number IDs
1. Left sidebar → **Phone Numbers** → **Buy Number**
2. Select an **Indian number** (+91) — if unavailable, pick US/UK (Vapi will still call Indian numbers)
3. After buying, click the number → Copy the **Phone Number ID** (UUID format like `abc123-def456-...`)
4. Each phone number pairs with its corresponding API key

### .env Config
```
VAPI_API_KEYS=your_key_1,your_key_2
VAPI_PHONE_NUMBER_IDS=phone_id_1,phone_id_2
```
Keys and phone IDs must be in matching order (key1↔id1, key2↔id2).

### ASHA Phone Number
Your Indian number `9042594791` needs the country code prefix:
```
ASHA_PHONE_NUMBER=+919042594791
```
**Always use +91 prefix for Indian numbers** — Vapi requires E.164 format.

---

## 2. EMAIL (Gmail SMTP to notify ASHA worker)

### Generate Gmail App Password
1. Go to https://myaccount.google.com/security
2. Enable **2-Step Verification** if not already on
3. Go to https://myaccount.google.com/apppasswords
4. App name: `Maa` → Click **Create**
5. Copy the 16-character password (like `abcd efgh ijkl mnop`)

### .env Config
```
EMAIL_USER=youremail@gmail.com
EMAIL_PASS=abcdefghijklmnop
ASHA_EMAIL=asha_worker_email@gmail.com
```
- `EMAIL_USER` = your Gmail that sends the alerts
- `EMAIL_PASS` = the 16-char app password (no spaces)
- `ASHA_EMAIL` = where the ASHA worker receives alerts

---

## 3. GOOGLE CALENDAR (Appointment Booking)

### Option A: Service Account (Recommended)

1. Go to https://console.cloud.google.com
2. Create a project (or use existing) → Enable **Google Calendar API**
3. Go to **APIs & Services** → **Credentials** → **Create Credentials** → **Service Account**
4. Name it `maa-calendar` → Create → Done
5. Click the service account → **Keys** tab → **Add Key** → **Create new key** → **JSON** → Download
6. Rename the downloaded file to `credentials.json` and place it in the `Maa/` root folder
7. Copy the service account email (looks like `maa-calendar@project.iam.gserviceaccount.com`)
8. Open Google Calendar → Settings of the calendar you want to use → **Share with specific people** → Add the service account email → Permission: **Make changes to events**
9. From that same calendar settings page, scroll to **Integrate calendar** → Copy the **Calendar ID**

### .env Config
```
GOOGLE_CALENDAR_ID=your_calendar_id@group.calendar.google.com
```

### Option B: Skip It
Calendar is optional. If not configured, appointments are still created in the database — just not synced to Google Calendar.

---

## Quick Checklist

| Service | What You Need | Where It Goes |
|---------|--------------|---------------|
| Vapi | API key(s) from dashboard | `VAPI_API_KEYS` |
| Vapi | Phone Number ID(s) | `VAPI_PHONE_NUMBER_IDS` |
| Vapi | ASHA phone with +91 | `ASHA_PHONE_NUMBER` |
| Email | Gmail address | `EMAIL_USER` |
| Email | App password (16 chars) | `EMAIL_PASS` |
| Email | ASHA worker email | `ASHA_EMAIL` |
| Calendar | credentials.json file | Project root |
| Calendar | Calendar ID | `GOOGLE_CALENDAR_ID` |
