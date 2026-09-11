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
# SOLAR PRODUCTION DROP ALERT
# ------------------------------------------------------------
# The alert only becomes active AFTER solar production has
# reached the trigger level.
#
# 2.0 kW = 2,000 W
# 0.7 kW = 700 W
#
# Example:
#
# Production reaches >= 2.0 kW
#             ↓
# Trigger is reached
#             ↓
# Production later falls below 0.7 kW
#             ↓
# Send notification

PRODUCTION_TRIGGER = 2.0
PRODUCTION_DROP_BELOW = 0.7

PRODUCTION_DROP_MESSAGE = (
    "Solar production dropped sharply — "
    "possible heavy cloud/rain."
)

# ------------------------------------------------------------
# CHARGING ALERTS
# ------------------------------------------------------------

CHARGING_ALERTS = {
    80: "Battery passed 80%",
    90: "Battery passed 90%",
    99: "Battery nearly full"
}

# ------------------------------------------------------------
# DISCHARGING ALERTS
# ------------------------------------------------------------

DISCHARGING_ALERTS = {
    95: "Battery dropped below 95%",
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

AC_WARNING_ENABLED = True

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
        "ac_warning_sent": False,
        "production_trigger_reached": False,
        "production_drop_alert_sent": False
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
        print(
            "Could not read state.json. Creating new state.")
        return create_default_state()

    # Make sure required sections exist
    state.setdefault("charging",{})
    state.setdefault("discharging",{})
    state.setdefault("full_battery_sent",False)
    state.setdefault("reached_100",False)
    state.setdefault("ac_warning_sent",False)
    state.setdefault("production_trigger_reached",False)
    state.setdefault("production_drop_alert_sent",False)

    # Add newly configured charging thresholds

    for threshold in CHARGING_ALERTS:
        state["charging"].setdefault(
            str(threshold),
            False
        )

    # Add newly configured discharging thresholds

    for threshold in DISCHARGING_ALERTS:
        state["discharging"].setdefault(
            str(threshold),
            False
        )
    return state


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state,f,indent=2)


# ============================================================
# DEYE API — AUTHENTICATION
# ============================================================

def get_access_token():

    password_hash = hashlib.sha256(
        DEYE_PASSWORD.encode("utf-8")
    ).hexdigest()

    url = (f"{DEYE_BASE_URL}/account/token")

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


# ============================================================
# GET STATION + INVERTER DATA
# ============================================================

def get_station_data(access_token):

    headers = {
        "Authorization": (
            f"Bearer {access_token}"
        ),
        "Content-Type": "application/json"
    }

    # ========================================================
    # 1. GET STATION DATA
    # ========================================================

    station_url = (
        f"{DEYE_BASE_URL}/station/latest"
    )

    station_payload = {
        "stationId": STATION_ID
    }

    station_response = requests.post(
        station_url,
        headers=headers,
        json=station_payload,
        timeout=30
    )

    station_response.raise_for_status()

    station_result = (
        station_response.json()
    )

    if not station_result.get("success"):

        raise Exception(
            "Deye station request failed: "
            f"{station_result}"
        )

    print("Deye station response received.")

    if "data" in station_result:
        latest = station_result["data"]
    else:
        latest = station_result
        
    if "batterySOC" not in latest:
        raise Exception(
            "Battery SOC not found in Deye response: "
            f"{station_result}"
        )

    soc = float(latest["batterySOC"])

    print("RAW Deye station data:")

    print(json.dumps(latest,indent=2))

    # This value is intentionally printed for comparison.
    #
    # DO NOT use it for the production alert because your
    # station endpoint was reporting 4.0 kW while the inverter
    # was actually producing only a few watts.

    print(
        f"Station generationPower: "
        f"{latest.get('generationPower')} kW"
    )

    # ========================================================
    # 2. FIND DEVICES CONNECTED TO THE STATION
    # ========================================================

    device_list_url = (
        f"{DEYE_BASE_URL}/station/device"
    )

    device_list_payload = {
        "stationIds": [STATION_ID],
        "page": 1,
        "size": 20
    }

    device_list_response = requests.post(
        device_list_url,
        headers=headers,
        json=device_list_payload,
        timeout=30
    )

    device_list_response.raise_for_status()

    device_list_result = (
        device_list_response.json()
    )

    if not device_list_result.get("success"):

        raise Exception(
            "Deye station device request failed: "
            f"{device_list_result}"
        )

    devices = device_list_result.get(
        "deviceListItems",
        []
    )

    if not devices:

        raise Exception(
            "No devices found for station "
            f"{STATION_ID}: "
            f"{device_list_result}"
        )

    print(
        "Deye station devices:"
    )

    print(
        json.dumps(
            devices,
            indent=2
        )
    )

    # ========================================================
    # 3. FIND INVERTER DEVICES
    # ========================================================

    inverter_devices = [
        device
        for device in devices
        if device.get("deviceType") == "INVERTER"
    ]

    if not inverter_devices:

        raise Exception(
            "No inverter device found. "
            f"Devices returned: {devices}"
        )

    print(
        "Deye inverter devices:"
    )

    print(
        json.dumps(
            inverter_devices,
            indent=2
        )
    )

    device_sns = [
        device["deviceSn"]
        for device in inverter_devices
        if device.get("deviceSn")
    ]

    if not device_sns:

        raise Exception(
            "No inverter device serial numbers found."
        )

    print(
        "Querying Deye device SNs: "
        f"{device_sns}"
    )

    # ========================================================
    # 4. GET INVERTER TELEMETRY
    # ========================================================

    device_latest_url = (
        f"{DEYE_BASE_URL}/device/latest"
    )

    device_latest_payload = {
        "deviceList": device_sns
    }

    device_latest_response = requests.post(
        device_latest_url,
        headers=headers,
        json=device_latest_payload,
        timeout=30
    )

    device_latest_response.raise_for_status()

    device_latest = (
        device_latest_response.json()
    )

    if not device_latest.get("success"):

        raise Exception(
            "Deye device request failed: "
            f"{device_latest}"
        )

    print(
        "RAW Deye device data:"
    )

    print(
        json.dumps(
            device_latest,
            indent=2
        )
    )

    device_data_list = (
        device_latest.get(
            "deviceDataList",
            []
        )
    )

    if not device_data_list:

        raise Exception(
            "Deye returned no device telemetry. "
            f"Requested devices: {device_sns}. "
            f"Response: {device_latest}"
        )

    # ========================================================
    # 5. READ INVERTER TELEMETRY
    # ========================================================

    total_generation_watts = 0.0

    found_total_gen_power = False

    for device_result in device_data_list:

        data_list = device_result.get(
            "dataList",
            []
        )

        telemetry = {
            item["key"]: item.get("value")
            for item in data_list
            if item.get("key")
        }

        print(
            "Deye inverter telemetry:"
        )

        print(
            json.dumps(
                telemetry,
                indent=2
            )
        )

        # ----------------------------------------------------
        # THIS IS THE IMPORTANT VALUE
        #
        # TotalGenPower = instantaneous generator/PV output
        # reported in W.
        # ----------------------------------------------------

        if "TotalGenPower" in telemetry:

            total_generation_watts += float(
                telemetry["TotalGenPower"]
            )

            found_total_gen_power = True

    if not found_total_gen_power:

        raise Exception(
            "TotalGenPower was not found in Deye "
            "inverter telemetry."
        )

    # ========================================================
    # 6. CONVERT WATTS TO KW
    # ========================================================

    production = (
        total_generation_watts / 1000.0
    )

    print(
        f"Battery SOC: {soc}%"
    )

    print(
        f"Station generationPower: "
        f"{latest.get('generationPower')} kW"
    )

    print(
        f"Inverter TotalGenPower: "
        f"{total_generation_watts} W"
    )

    print(
        f"Solar production used by alert: "
        f"{production:.3f} kW"
    )

    return soc, production


# ============================================================
# NTFY
# ============================================================

def send_notification(
    message,
    priority=NORMAL_PRIORITY,
    tags="battery"
):

    url = (
        f"https://ntfy.sh/{NTFY_TOPIC}"
    )

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

    print(
        f"Notification sent: {message}"
    )


# ============================================================
# CHARGING ALERTS
# ============================================================

def check_charging_alerts(
    soc,
    state
):

    for threshold, message in sorted(
        CHARGING_ALERTS.items()
    ):

        state_key = str(
            threshold
        )

        if soc >= threshold:

            if not state["charging"][state_key]:

                send_notification(
                    f"{message} — "
                    f"now at {soc:.0f}%",
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

def check_discharging_alerts(
    soc,
    state
):

    for threshold, message in sorted(
        DISCHARGING_ALERTS.items(),
        reverse=True
    ):

        state_key = str(
            threshold
        )

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
                    f"{message} — "
                    f"now at {soc:.0f}%",
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

def check_full_battery(
    soc,
    state
):

    if soc >= FULL_BATTERY:

        # Remember that battery actually reached 100%

        state["reached_100"] = True

        # Re-arm AC warning for this new full-charge cycle

        state["ac_warning_sent"] = False

        if not state["full_battery_sent"]:

            send_notification(
                f"Battery fully charged — "
                f"{FULL_BATTERY}%",
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

def check_ac_warning(
    soc,
    state
):

    if not AC_WARNING_ENABLED:

        return

    # Only activate this warning after the battery
    # has actually reached 100%

    if not state["reached_100"]:

        return

    # Battery has fallen below configured AC threshold

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
# SOLAR PRODUCTION DROP WARNING
# ============================================================

def check_production_drop(
    production,
    state
):

    # --------------------------------------------------------
    # STEP 1:
    # Production reaches the high trigger.
    # This ARMS the drop alert.
    # --------------------------------------------------------

    if production >= PRODUCTION_TRIGGER:

        state[
            "production_trigger_reached"
        ] = True

        # Allow a future drop notification

        state[
            "production_drop_alert_sent"
        ] = False

        print(
            f"Production trigger reached: "
            f"{production:.3f} kW"
        )

        return

    # --------------------------------------------------------
    # STEP 2:
    # Don't alert if production has never reached
    # the high trigger.
    # --------------------------------------------------------

    if not state[
        "production_trigger_reached"
    ]:

        print(
            "Production trigger has not been reached yet."
        )

        return

    # --------------------------------------------------------
    # STEP 3:
    # Production was previously high and has now
    # dropped below the low threshold.
    # --------------------------------------------------------

    if production < PRODUCTION_DROP_BELOW:

        if not state[
            "production_drop_alert_sent"
        ]:

            send_notification(
                PRODUCTION_DROP_MESSAGE
                + f" Now at {production:.2f} kW.",
                WARNING_PRIORITY,
                "warning,partly_sunny"
            )

            state[
                "production_drop_alert_sent"
            ] = True

            print(
                f"Production drop alert sent: "
                f"{production:.3f} kW"
            )

    else:

        print(
            f"Production is below trigger but "
            f"not low enough for drop alert: "
            f"{production:.3f} kW"
        )


# ============================================================
# MAIN BATTERY CHECK
# ============================================================

def check_battery(
    soc,
    production,
    state
):

    print(
        "Checking battery alerts..."
    )

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

    check_production_drop(
        production,
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

    soc, production = get_station_data(
        access_token
    )

    check_battery(
        soc,
        production,
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