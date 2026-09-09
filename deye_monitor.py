import os
import json
import hashlib
import requests

# ==============================
# Deye Configuration
# ==============================

DEYE_BASE_URL = "https://eu1-developer.deyecloud.com/v1.0"

STATION_ID = 62615671

# ==============================
# Battery Alert Settings
# ==============================

LOW_THRESHOLD = 31
HIGH_THRESHOLDS = [79, 89, 99]
FULL_THRESHOLD = 100
AC_WARNING_THRESHOLD = 95

STATE_FILE = "state.json"

# ==============================
# Get Secrets from GitHub
# ==============================

DEYE_APP_ID = os.environ["DEYE_APP_ID"]
DEYE_APP_SECRET = os.environ["DEYE_APP_SECRET"]
DEYE_EMAIL = os.environ["DEYE_EMAIL"]
DEYE_PASSWORD = os.environ["DEYE_PASSWORD"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]


# ==============================
# State Handling
# ==============================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "low_30_sent": False,
            "high_80_sent": False,
            "high_90_sent": False,
            "high_100_sent": False,
            "reached_100": False,
            "below_95_sent": False
        }

    with open(STATE_FILE, "r") as f:
        state = json.load(f)
        
    state.setdefault("full_100_sent", False)
    state.setdefault("reached_100", False)
    state.setdefault("below_95_sent", False)

    return state


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ==============================
# Deye Authentication
# ==============================

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
        raise Exception(f"Deye authentication failed: {data}")

    return data["accessToken"]


# ==============================
# Get Battery Information
# ==============================

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
        raise Exception(f"Deye station request failed: {data}")
    
    print("Deye station response received.")
    
    if "data" in data:
        latest = data["data"]
    else:
        latest = data
    
    if "batterySOC" not in latest:
        raise Exception(f"Battery SOC not found in Deye response: {data}")
    
    soc = float(latest["batterySOC"])

    print(f"Battery SOC: {soc}%")

    return soc


# ==============================
# Send iPhone Notification
# ==============================

def send_notification(title, message, priority="default", tags="battery"):

    url = f"https://ntfy.sh/{NTFY_TOPIC}"

    headers = {
        "Title": title,
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


# ==============================
# Battery Alert Logic
# ==============================

def check_battery(soc, state):

    # --------------------------------
    # LOW BATTERY
    # --------------------------------

    if soc <= LOW_THRESHOLD:

        if not state["low_30_sent"]:

            send_notification(
                "Deye Battery",
                f"Battery dropped to {soc:.0f}%",
                "high",
                "warning,battery"
            )

            state["low_30_sent"] = True

    elif soc > LOW_THRESHOLD:

        state["low_30_sent"] = False


    # --------------------------------
    # HIGH BATTERY THRESHOLDS
    # 79%, 89%, 99%
    # --------------------------------

    threshold_state = {
        HIGH_THRESHOLDS[0]: "high_80_sent",
        HIGH_THRESHOLDS[1]: "high_90_sent",
        HIGH_THRESHOLDS[2]: "high_100_sent"
    }

    for threshold, state_key in threshold_state.items():

        if soc >= threshold:

            if not state[state_key]:

                if threshold == HIGH_THRESHOLDS[0]:

                    message = (
                        f"Battery reached {soc:.0f}% — passed 80%"
                    )

                elif threshold == HIGH_THRESHOLDS[1]:

                    message = (
                        f"Battery reached {soc:.0f}% — passed 90%"
                    )

                else:

                    message = (
                        f"Battery reached {soc:.0f}% — nearly full"
                    )

                send_notification(
                    "Deye Battery",
                    message,
                    "default",
                    "battery,arrow_up"
                )

                state[state_key] = True

        else:

            state[state_key] = False


    # --------------------------------
    # FULL BATTERY — 100%
    # --------------------------------

    if soc >= FULL_THRESHOLD:

        # Remember that the battery has actually
        # reached full charge
        state["reached_100"] = True

        # A new full-charge cycle allows the
        # below-95% warning again
        state["below_95_sent"] = False

        if not state.get("full_100_sent", False):

            send_notification(
                "Deye Battery",
                "Battery fully charged — 100%",
                "high",
                "battery,white_check_mark"
            )

            state["full_100_sent"] = True

    else:

        state["full_100_sent"] = False


    # --------------------------------
    # AFTER 100%:
    # BATTERY BELOW 95%
    # --------------------------------

    if state["reached_100"] and soc < AC_WARNING_THRESHOLD:

        if not state["below_95_sent"]:

            send_notification(
                "Deye Battery",
                f"Battery dropped below {AC_WARNING_THRESHOLD}% — "
                f"now at {soc:.0f}%. Consider turning off AC.",
                "high",
                "warning,battery"
            )

            state["below_95_sent"] = True


# ==============================
# MAIN
# ==============================

def main():

    print("Starting Deye battery check...")

    state = load_state()

    access_token = get_access_token()

    soc = get_battery_soc(access_token)

    check_battery(soc, state)

    save_state(state)

    print("Check completed successfully.")


if __name__ == "__main__":
    main()
