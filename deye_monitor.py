import os
import json
import hashlib
import requests

# ============================================================
# USER SETTINGS — CHANGE VALUES HERE ONLY
# ============================================================

# Deye station
STATION_ID = 62615671

# ------------------------------------------------------------
# CHARGING ALERTS
# ------------------------------------------------------------
# Alert when battery reaches/passes these levels while charging.
#
# Example:
# 80: "Battery passed 80%"
#
# To add another alert:
# 70: "Battery passed 70%"
#
CHARGING_ALERTS = {
    80: "Battery passed 80%",
    90: "Battery passed 90%",
    99: "Battery nearly full"
}

# ------------------------------------------------------------
# DISCHARGING ALERTS
# ------------------------------------------------------------
# Alert when battery drops BELOW these levels.
#
# Example:
# 60: "Battery dropped below 60%"
#
DISCHARGING_ALERTS = {
    80: "Battery dropped below 80%",
    60: "Battery dropped below 60%",
    40: "Battery dropped below 40%",
    31: "CRITICAL: Battery is very low"
}

# ------------------------------------------------------------
# FULL BATTERY
# ------------------------------------------------------------

FULL_BATTERY = 100

# ------------------------------------------------------------
# AC WARNING
# ------------------------------------------------------------

# Enable/disable the special AC warning
AC_WARNING_ENABLED = True

# After the battery reaches 100%, send an alert
# when it later drops below this percentage.
AC_WARNING_BELOW = 95

AC_WARNING_MESSAGE = (
    "Battery dropped below 95% — "
    "consider turning off AC."
)

# ------------------------------------------------------------
# NOTIFICATION PRIORITY
# ------------------------------------------------------------

# Options:
# "min"
# "low"
# "default"
# "high"
# "max"

NORMAL_PRIORITY = "default"
WARNING_PRIORITY = "high"

# ============================================================
# SYSTEM SETTINGS — DON'T CHANGE THESE
# ============================================================

DEYE_BASE_URL = (
    "https://eu1-developer.deyecloud.com/v1.0"
)

STATE_FILE = "state.json"

DEYE_APP_ID = os.environ["DEYE_APP_ID"]
DEYE_APP_SECRET = os.environ["DEYE_APP_SECRET"]
DEYE_EMAIL = os.environ["DEYE_EMAIL"]
DEYE_PASSWORD = os.environ["DEYE_PASSWORD"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]


# ============================================================
# STATE MANAGEMENT
# ============================================================

def create_default_state():
    state = {
        "charging": {},
        "discharging": {},
        "full_battery_sent": False,
        "reached_100": False,
        "ac_warning_sent": False
    }

    for threshold in CHARGING_ALERTS:
        state["charging"][str(threshold)] = False

    for threshold in DISCHARGING_ALERTS:
        state["discharging"][str(threshold)] = False

    return state


def load_state():
    if not os.path.exists(STATE_FILE):
        return create_default_state()

    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    except Exception:
        print("Could not read state.json. Creating new state.")
        return create_default_state()

    # Make sure required sections exist
    state.setdefault("charging", {})
    state.setdefault("discharging", {})
    state.setdefault("full_battery_sent", False)
    state.setdefault("reached_100", False)
    state.setdefault("ac_warning_sent", False)

    # Add newly configured thresholds automatically
    for threshold in CHARGING_ALERTS:
        state["charging"].setdefault(
            str(threshold),
            False
        )

    for threshold in DISCHARGING_ALERTS:
        state["discharging"].setdefault(
            str(threshold),
            False
        )

    return state


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ============================================================
# DEYE API
# ============================================================

def get_access_token():

    password_hash = hashlib.sha256(
        DEYE_PASSWORD.encode("utf-8")
    ).hexdigest()

    url = f"{DEYE_BASE_URL}/account/token"

    payload = {
        "appSecret": DEYE_APP_SECRET,
        "email": DEYE_EMAIL,
        "password": password_hash
    }

    response = requests.post(
        url,
        params={"appId": DEYE_APP_ID},
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("success"):
        raise Exception(
            f"Deye authentication failed: {data}"
        )

    return data["accessToken"]


def get_battery_soc(access_token):

    url = f"{DEYE_BASE_URL}/station/latest"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "stationId": STATION_ID
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("success"):
        raise Exception(
            f"Deye station request failed: {data}"
        )

    print("Deye station response received.")

    if "data" in data:
        latest = data["data"]
    else:
        latest = data

    if "batterySOC" not in latest:
        raise Exception(
            f"Battery SOC not found in Deye response: {data}"
        )

    soc = float(latest["batterySOC"])

    print(f"Battery SOC: {soc}%")

    return soc


# ============================================================
# NTFY
# ============================================================

def send_notification(
    message,
    priority=NORMAL_PRIORITY,
    tags="battery"
):

    url = f"https://ntfy.sh/{NTFY_TOPIC}"

    headers = {
        "Title": "Deye Battery",
        "Priority": priority,
        "Tags": tags
    }

    response = requests.post(
        url,
        headers=headers,
        data=message.encode("utf-8"),
        timeout=30
    )

    response.raise_for_status()

    print(f"Notification sent: {message}")


# ============================================================
# CHARGING ALERTS
# ============================================================

def check_charging_alerts(soc, state):

    for threshold, message in sorted(
        CHARGING_ALERTS.items()
    ):

        state_key = str(threshold)

        if soc >= threshold:

            if not state["charging"][state_key]:

                send_notification(
                    f"{message} — now at {soc:.0f}%",
                    NORMAL_PRIORITY,
                    "battery,arrow_up"
                )

                state["charging"][state_key] = True

        else:

            # Re-arm when battery falls below threshold
            state["charging"][state_key] = False


# ============================================================
# DISCHARGING ALERTS
# ============================================================

def check_discharging_alerts(soc, state):

    for threshold, message in sorted(
        DISCHARGING_ALERTS.items(),
        reverse=True
    ):

        state_key = str(threshold)

        if soc < threshold:

            if not state["discharging"][state_key]:

                # 31% and below gets high priority
                if threshold <= 31:
                    priority = WARNING_PRIORITY
                    tags = "warning,battery"
                else:
                    priority = NORMAL_PRIORITY
                    tags = "battery,arrow_down"

                send_notification(
                    f"{message} — now at {soc:.0f}%",
                    priority,
                    tags
                )

                state["discharging"][state_key] = True

        else:

            # Re-arm when battery goes back above threshold
            state["discharging"][state_key] = False


# ============================================================
# FULL BATTERY
# ============================================================

def check_full_battery(soc, state):

    if soc >= FULL_BATTERY:

        # Remember that the battery actually reached 100%
        state["reached_100"] = True

        # Re-arm AC warning for this new full-charge cycle
        state["ac_warning_sent"] = False

        if not state["full_battery_sent"]:

            send_notification(
                f"Battery fully charged — {FULL_BATTERY}%",
                WARNING_PRIORITY,
                "battery,white_check_mark"
            )

            state["full_battery_sent"] = True

    else:

        # Allow another full-battery notification
        # after battery leaves 100%
        state["full_battery_sent"] = False


# ============================================================
# AC WARNING
# ============================================================

def check_ac_warning(soc, state):

    if not AC_WARNING_ENABLED:
        return

    # Only activate this warning after the battery
    # has actually reached 100%
    if not state["reached_100"]:
        return

    # Battery has fallen below the configured AC threshold
    if soc < AC_WARNING_BELOW:

        if not state["ac_warning_sent"]:

            send_notification(
                AC_WARNING_MESSAGE
                + f" Now at {soc:.0f}%.",
                WARNING_PRIORITY,
                "warning,battery"
            )

            state["ac_warning_sent"] = True


# ============================================================
# MAIN BATTERY CHECK
# ============================================================

def check_battery(soc, state):

    print("Checking battery alerts...")

    check_charging_alerts(
        soc,
        state
    )

    check_discharging_alerts(
        soc,
        state
    )

    check_full_battery(
        soc,
        state
    )

    check_ac_warning(
        soc,
        state
    )


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():

    print("================================")
    print("Starting Deye battery check...")
    print("================================")

    state = load_state()

    access_token = get_access_token()

    soc = get_battery_soc(
        access_token
    )

    check_battery(
        soc,
        state
    )

    save_state(
        state
    )

    print("================================")
    print("Check completed successfully.")
    print("================================")


if __name__ == "__main__":
    main()
