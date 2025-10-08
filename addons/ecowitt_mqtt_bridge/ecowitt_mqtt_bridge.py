#!/usr/bin/env python3
# Ecowitt MQTT → Home Assistant Discovery
# v0.70
# - Offizielle Local HTTP API:
#     /get_livedata_info  (Livewerte)
#     /get_sensors_info?page=N  (Sensor-Mapping inkl. img + id)
# - GUI-Login des Gateways wird für die Local-API nicht benötigt
# - Aggregierte Gateway-Werte aus dem MQTT-Upload (tempf, humidity, wind*, uv, solarradiation, vpd, rain*)
# - LAN-spezifisch:
#     * Indoor (wh25) → Gateway-Gerät
#     * piezoRain + WS90-Felder → eigenes Gerät WH90(<id>)
#     * normale rain-Werte → WH69(<id>), wenn im selben Tick kein Piezo vorhanden ist
#     * common_list (Temp/Wind/UV/Solar) bleibt standardmäßig AUS (Duplikate vermeiden),
#       kann über --publish-lan-common oder Env PUBLISH_LAN_COMMON=1 aktiviert werden

import argparse
import json
import os
import sys
import re
import time
from datetime import datetime
from urllib.parse import parse_qs

import paho.mqtt.client as mqtt
import requests


# ---------- logging ----------
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr)


# ---------- unit helpers ----------
def f2c(v): return (float(v) - 32.0) * 5 / 9
def mph2ms(v): return float(v) * 0.44704
def inch2mm(v): return float(v) * 25.4

def try_float(x):
    s = str(x).strip()
    try:
        return float(s)
    except Exception:
        m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)", s)
        return float(m.group(1)) if m else None


# ---------- parse Ecowitt MQTT (flat, URL-encoded or JSON) ----------
def parse_payload(b: bytes):
    s = b.decode("utf-8", "ignore").strip()
    # JSON dict?
    try:
        d = json.loads(s)
        if isinstance(d, dict):
            # Manche Firmwares schicken eine Ein-Schlüssel-JSON mit urlencodetem String
            if len(d) == 1 and isinstance(next(iter(d.values())), str):
                inner = next(iter(d.values()))
                if "=" in inner and "&" in inner:
                    qs = parse_qs(inner, keep_blank_values=True)
                    return {k: v[0] for k, v in qs.items()}
            return d
    except Exception:
        pass
    # URL-encoded key=value&...
    if "=" in s and "&" in s:
        qs = parse_qs(s, keep_blank_values=True)
        return {k: v[0] for k, v in qs.items()}
    return {}


# ---------- bekannte Key-Bezeichnungen (LAN-IDs) ----------
FRIENDLY_BY_ID = {
    "0x02": ("Outdoor Temperature", "°C", "temperature", "measurement"),
    "3":    ("Apparent Temperature", "°C", "temperature", "measurement"),  # NEU
    "5":    ("VPD", "kPa", None, "measurement"),                           # NEU
    "0x03": ("Dew Point", "°C", None, "measurement"),
    "0x07": ("Outdoor Humidity", "%", "humidity", "measurement"),
    "0x0B": ("Wind Speed", "m/s", None, "measurement"),
    "0x0C": ("Wind Gust", "m/s", None, "measurement"),
    "0x19": ("Wind Speed (avg10m)", "m/s", None, "measurement"),
    "0x0A": ("Wind Direction", "°", None, "measurement"),
    "0x6D": ("Wind Direction (avg10m)", "°", None, "measurement"),
    # Einige Firmwares zeigen "Kfc"; wir veröffentlichen in HA als W/m²
    "0x15": ("Solar Radiation", "W/m²", None, "measurement"),
    "0x17": ("UV Index", None, None, "measurement"),
    "0x0D": ("Rain (Total)", "mm", "precipitation", "total_increasing"),
    "0x0E": ("Rain Rate", "mm/h", None, "measurement"),
    "0x7C": ("Rain (Since Reset)", "mm", "precipitation", "total_increasing"),
    "0x10": ("Rain (Daily)", "mm", "precipitation", "total_increasing"),
    "0x11": ("Rain (Weekly)", "mm", "precipitation", "total_increasing"),
    "0x12": ("Rain (Monthly)", "mm", "precipitation", "total_increasing"),
    "0x13": ("Rain (Yearly)", "mm", "precipitation", "total_increasing"),
}

# Aggregierte Gatewayfelder aus dem MQTT-Upload (imperial → metric konvertiert)
AGGREGATE_SENSORS = [
    ("tempf",          "Outdoor Temperature (Agg)", "°C",  "temperature",  "measurement",       f2c),
    ("humidity",       "Outdoor Humidity (Agg)",    "%",   "humidity",     "measurement",       float),
    ("windspeedmph",   "Wind Speed (Agg)",          "m/s", None,           "measurement",       mph2ms),
    ("windgustmph",    "Wind Gust (Agg)",           "m/s", None,           "measurement",       mph2ms),
    ("winddir",        "Wind Direction (Agg)",      "°",   None,           "measurement",       float),
    ("uv",             "UV Index (Agg)",            None,  None,           "measurement",       float),
    ("solarradiation", "Solar Radiation (Agg)",     "W/m²",None,           "measurement",       float),
    ("vpd",            "VPD (Agg)",                 "kPa", None,           "measurement",       float),
    ("rainratein",     "Rain Rate (Agg)",           "mm/h",None,           "measurement",       inch2mm),
    ("dailyrainin",    "Rain (Daily) (Agg)",        "mm",  "precipitation","total_increasing",  inch2mm),
]


# ---------- HA device builders ----------
def build_gateway_device(passkey, model):
    return {
        "identifiers": [f"ecowitt_passkey_{passkey}"],
        "manufacturer": "Ecowitt",
        "model": str(model),
        "name": f"Ecowitt {model} ({str(passkey)[:6]})",
    }

def build_sensor_device(img: str, hwid: str):
    model_name = (img or "Sensor").upper()
    return {
        "identifiers": [f"ecowitt_hw_{model_name}_{hwid}"],
        "manufacturer": "Ecowitt",
        "model": model_name,
        "name": f"Ecowitt {model_name} ({hwid})",
    }


# ---------- LAN API (offizielle Endpunkte) ----------
def http_get_json(session: requests.Session, base: str, path: str, timeout: float):
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    try:
        r = session.get(url, timeout=timeout)
        log(f"[LAN] GET {url} -> {r.status_code}")
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f"[LAN] GET {url} failed: {e}")
    return None

def fetch_sensor_mapping_official(session, base, timeout):
    """/get_sensors_info?page=N → Liste mit {img, id, ...}"""
    all_items = []
    for page in range(1, 6):
        data = http_get_json(session, base, f"/get_sensors_info?page={page}", timeout)
        if not isinstance(data, list):
            break
        if not data:
            break
        for it in data:
            if isinstance(it, dict) and it.get("id") and it.get("img"):
                all_items.append(it)
        if len(data) < 30:
            break
    if all_items:
        log(f"[LAN] sensors_info: {len(all_items)} items")
    else:
        log("[LAN] sensors_info: none")
    return all_items

def active_ids_from_mapping(items):
    """Erzeuge dict wie {'wh90': 'B708', 'wh69': '12'} nur für echte gekoppelte Sensoren."""
    out = {}
    for it in items or []:
        img = (it.get("img") or "").lower()
        sid = str(it.get("id") or "").strip()
        if sid and sid not in ("FFFFFFFF", "FFFFFFFE"):
            out[img] = sid
    if out:
        pairs = ", ".join(f"{k}={v}" for k, v in out.items())
        log(f"[LAN] sensors_info active: {pairs}")
    return out

def fetch_live_official(session, base, timeout):
    """/get_livedata_info → dict mit common_list, rain, piezoRain, wh25, debug."""
    data = http_get_json(session, base, "/get_livedata_info", timeout)
    if isinstance(data, dict) and any(k in data for k in ("common_list","rain","piezoRain","wh25","debug")):
        has_hwid = False
        for grp in ("common_list","rain","piezoRain"):
            for it in (data.get(grp) or []):
                if isinstance(it, dict) and any(k in it for k in ("sid","hwid","img","id_st","idst")):
                    has_hwid = True
                    break
        log(f"[LAN] live-info has per-item hwid? {'yes' if has_hwid else 'no'}")
        return data
    return None


# ---------- Bridge ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", required=True)
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--username"); ap.add_argument("--password")
    ap.add_argument("--in-topic", default="ecowitt/#")
    ap.add_argument("--discovery-prefix", default="homeassistant")
    ap.add_argument("--state-prefix", default="ecowitt_ha")
    ap.add_argument("--client-id", default="ecowitt-bridge")
    ap.add_argument("--cleanup", action="store_true")
    # LAN API:
    ap.add_argument("--use-local-api", action="store_true")
    ap.add_argument("--gateway-base-url", default="")
    ap.add_argument("--lan-timeout", type=float, default=3.0)
    ap.add_argument("--map-refresh-sec", type=int, default=600)
    # NEU: LAN-common_list standardmäßig AUS (kein Flag = False)
    ap.add_argument("--publish-lan-common", action="store_true",
                    help="Publish LAN common_list (Temp/Wind/UV/Solar). Default off to avoid duplicates.")
    args = ap.parse_args()

    # alternativ via Env überschreibbar (PUBLISH_LAN_COMMON=1)
    env_plc = os.getenv("PUBLISH_LAN_COMMON", "")
    publish_lan_common = args.publish_lan_common or (env_plc.strip() in ("1","true","yes","on"))

    session = requests.Session() if args.use_local_api and args.gateway_base_url else None
    sensor_mapping = []
    last_map_fetch = 0.0

    cli = mqtt.Client(client_id=args.client_id, clean_session=True)
    if args.username:
        cli.username_pw_set(args.username, args.password or None)
    cli.will_set(f"{args.state_prefix}/status", payload="offline", qos=1, retain=True)

    # ---------- HA publish helpers ----------
    def publish_cfg(device_obj, uid_suffix, name, unit, devcls, stcls):
        uid = f"{uid_suffix}".lower()
        cfg_topic = f"{args.discovery_prefix}/sensor/{uid}/config"
        if args.cleanup:
            cli.publish(cfg_topic, payload="", qos=1, retain=True)
            return None
        cfg = {
            "name": name,
            "unique_id": uid,
            "state_topic": f"{args.state_prefix}/{uid}/state",
            "device": device_obj,
            "availability_topic": f"{args.state_prefix}/status",
            "state_class": stcls,
        }
        if unit is not None:
            cfg["unit_of_measurement"] = unit
        if devcls is not None:
            cfg["device_class"] = devcls
        cli.publish(cfg_topic, json.dumps(cfg), qos=1, retain=True)
        log(f"[DISCOVERY] {cfg_topic} → {name}")
        return cfg["state_topic"]

    def publish_value(uid_suffix, val):
        cli.publish(f"{args.state_prefix}/{uid_suffix.lower()}/state", str(val), qos=0, retain=False)

    # ---------- gateway aggregates from MQTT flat upload ----------
    def handle_flat_gateway(raw):
        passkey = raw.get("PASSKEY") or raw.get("passkey") or "unknown"
        model = raw.get("stationtype") or raw.get("model") or "GW3000"
        gw_device = build_gateway_device(passkey, model)
        for key, friendly, unit, devcls, stcls, conv in AGGREGATE_SENSORS:
            if key in raw:
                v = try_float(raw[key])
                if v is None:
                    continue
                try:
                    v = conv(v)
                except Exception:
                    continue
                if isinstance(v, float):
                    v = round(v, 3 if key.startswith("wind") else 2)
                uid = f"ecowitt_{passkey}_{key}"
                st = publish_cfg(gw_device, uid, friendly, unit, devcls, stcls)
                if st:
                    publish_value(uid, v)
        return passkey, model

    # ---------- LAN per-sensor ----------
    def refresh_mapping_if_needed():
        nonlocal sensor_mapping, last_map_fetch
        if not session:
            return
        now = time.time()
        if now - last_map_fetch < max(30, args.map_refresh_sec):
            return
        m = fetch_sensor_mapping_official(session, args.gateway_base_url, args.lan_timeout)
        if m:
            sensor_mapping = m
            last_map_fetch = now

    def handle_lan(passkey, model):
        if not session:
            return
        refresh_mapping_if_needed()

        live = fetch_live_official(session, args.gateway_base_url, args.lan_timeout)
        if not live:
            log("[LAN] live-data not available")
            return

        ids = active_ids_from_mapping(sensor_mapping)  # {'wh90': 'B708', 'wh69': '12', ...}
        wh90_id = ids.get("wh90")
        wh69_id = ids.get("wh69")

        # Indoor (wh25) → Gateway-Gerät
        gw_device = build_gateway_device(passkey, model)
        wh25 = live.get("wh25")
        if isinstance(wh25, list) and wh25:
            d = wh25[0]
            # tempinf
            if "intemp" in d:
                try:
                    v = float(str(d["intemp"]).replace(",", "."))
                    uid = f"ecowitt_{passkey}_tempinf"
                    st = publish_cfg(gw_device, uid, "Indoor Temperature", "°C", "temperature", "measurement")
                    if st: publish_value(uid, round(v, 2))
                except Exception:
                    pass
            # humidityin
            if "inhumi" in d:
                v = try_float(d["inhumi"])
                if v is not None:
                    uid = f"ecowitt_{passkey}_humidityin"
                    st = publish_cfg(gw_device, uid, "Indoor Humidity", "%", "humidity", "measurement")
                    if st: publish_value(uid, v)
            # pressure
            if "abs" in d:
                v = try_float(str(d["abs"]).split()[0])
                if v is not None:
                    uid = f"ecowitt_{passkey}_baromabsin"
                    st = publish_cfg(gw_device, uid, "Pressure (Absolute)", "hPa", "pressure", "measurement")
                    if st: publish_value(uid, round(v, 1))
            if "rel" in d:
                v = try_float(str(d["rel"]).split()[0])
                if v is not None:
                    uid = f"ecowitt_{passkey}_baromrelin"
                    st = publish_cfg(gw_device, uid, "Pressure (Relative)", "hPa", "pressure", "measurement")
                    if st: publish_value(uid, round(v, 1))

        # ---- PIEZO RAIN → immer WH90, wenn vorhanden ----
        if wh90_id:
            for it in (live.get("piezoRain") or []):
                kid = str(it.get("id"))
                raw = it.get("val")
                if raw is None:
                    continue
                m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)", str(raw))
                v = m.group(1) if m else raw
                device = build_sensor_device("wh90", wh90_id)
                friendly, unit, devcls, stcls = FRIENDLY_BY_ID.get(kid, (f"Sensor {kid}", None, None, "measurement"))
                num = try_float(v)
                if num is None:
                    continue
                uid = f"ecowitt_wh90_{wh90_id}_{kid}"
                st = publish_cfg(device, uid, friendly, unit, devcls, stcls)
                if st:
                    publish_value(uid, round(num, 3 if kid in {"0x0B","0x0C","0x19"} else 2))

        # ---- „normale“ RAIN → wenn kein Piezo-Wert im Tick, gib sie WH69 ----
        piezo_present = any(x.get("id") == "srain_piezo" for x in (live.get("piezoRain") or []))
        if wh69_id and not piezo_present:
            for it in (live.get("rain") or []):
                kid = str(it.get("id"))
                raw = it.get("val")
                if raw is None:
                    continue
                m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)", str(raw))
                v = m.group(1) if m else raw
                device = build_sensor_device("wh69", wh69_id)
                friendly, unit, devcls, stcls = FRIENDLY_BY_ID.get(kid, (f"Sensor {kid}", None, None, "measurement"))
                num = try_float(v)
                if num is None:
                    continue
                uid = f"ecowitt_wh69_{wh69_id}_{kid}"
                st = publish_cfg(device, uid, friendly, unit, devcls, stcls)
                if st:
                    publish_value(uid, round(num, 2))

        # ---- common_list (Temp/Wind/UV/Solar) → optional (Default: AUS, um Duplikate zu vermeiden) ----
        if publish_lan_common:
            for it in (live.get("common_list") or []):
                key_id = str(it.get("id"))
                raw = it.get("val")
                if raw is None:
                    continue
                friendly, unit, devcls, stcls = FRIENDLY_BY_ID.get(key_id, (f"Sensor {key_id}", None, None, "measurement"))
                if isinstance(raw, str):
                    m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)", raw)
                    raw_val = m.group(1) if m else raw
                else:
                    raw_val = raw
                num = try_float(raw_val)
                if num is None:
                    continue
                # Als Aggregat am Gateway (damit keine Duplikate zu WS90/WH69 entstehen)
                uid = f"ecowitt_{passkey}_{key_id}"
                st = publish_cfg(gw_device, uid, f"{friendly} (Agg)", unit, devcls, stcls)
                if st:
                    publish_value(uid, round(num, 3 if key_id in {"0x0B","0x0C","0x19"} else 2))

    # ---------- MQTT callbacks ----------
    def on_connect(c, u, f, rc):
        if rc == 0:
            for t in [t.strip() for t in args.in_topic.split(",") if t.strip()]:
                c.subscribe(t, qos=0)
                log(f"[MQTT] Subscribed to {t}")
            c.publish(f"{args.state_prefix}/status", "online", qos=1, retain=True)
            log("[MQTT] Connected")
        else:
            log(f"[MQTT] connect failed: rc={rc}")

    def on_message(c, u, msg):
        raw_txt = msg.payload.decode("utf-8", "ignore")
        log(f"[RECV] topic={msg.topic} bytes={len(msg.payload)} sample='{raw_txt[:80]}'")
        raw = parse_payload(msg.payload)
        if not raw:
            log("[RECV] parse failed")
            return
        passkey = raw.get("PASSKEY") or raw.get("passkey") or "unknown"
        model = raw.get("stationtype") or raw.get("model") or "GW3000"
        handle_flat_gateway(raw)
        if session:
            handle_lan(passkey, model)
        else:
            log("[LAN] disabled (set --use-local-api/--gateway-base-url)")

    # ---------- run ----------
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.connect(args.broker, args.port, 60)
    cli.loop_forever()


if __name__ == "__main__":
    main()
