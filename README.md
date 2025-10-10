
# ecowitt_mqtt_addon

An Ecowitt MQTT Bridge as ADD ON for Home Assistant 2025+

---

# 🌦️ Ecowitt MQTT Bridge Add-on

The **Ecowitt MQTT Bridge Add-on** for [Home Assistant](https://www.home-assistant.io/) parses MQTT uploads from Ecowitt weather devices (e.g. GW1100, GW2000, GW3000) and optionally reads data via the Ecowitt LAN API.
It automatically publishes all sensor data using **Home Assistant MQTT Discovery**, allowing you to use your Ecowitt sensors natively in Home Assistant — no manual MQTT setup required.

---

## 🚀 Features

* Receives data from **Ecowitt Wi-Fi gateways** via MQTT or the LAN API
* Publishes all sensors dynamically via **Home Assistant MQTT Discovery**
* Supports **LAN API polling** for local data without cloud dependency
* Automatically cleans up or updates sensors when devices change
* Simple **web-based configuration** from the Home Assistant UI
* Compatible with **core-mosquitto** and external MQTT brokers
* Lightweight – written in Python and runs as a native HA Add-on

---

## 🧩 Installation

## 🌐 Enabling MQTT Upload in Your Ecowitt Gateway

Before the add-on can receive data, you **must enable MQTT upload** in your Ecowitt Gateway’s web interface.

### Steps

1. Open your Ecowitt Gateway’s configuration page in your browser — usually something like:

   ```
   http://<your-gateway-ip>/
   ```
2. Navigate to:
   **Customized → Protocol Type Same As → MQTT**
3. Enable the **Customized** option.
4. Fill in the fields as shown below.

| Field               | Example Value          | Description                                  |
| ------------------- | ---------------------- | -------------------------------------------- |
| **Host**            | `192.168.0.5`          | The IP address of your Home Assistant server |
| **Port**            | `1883`                 | MQTT port                                    |
| **Publish Topic**   | `ecowitt/048308785133` | Topic where data will be published (the number usually is already there           |
| **Transport**       | `MQTT over TCP`        | Communication type                           |
| **Upload Interval** | `60`                   | How often data is sent (in seconds)          |
| **Keep Alive**      | `60`                   | MQTT keepalive time                          |
| **Client Name**     | `GW3000`               | Name of your Ecowitt gateway                 |
| **Client ID**       | `ecowitt_gw3000`       | Unique MQTT client identifier                |
| **Username**        | `ecowitt_mqtt`         | Your MQTT username (from HA broker)          |
| **Password**        | `********`             | Your MQTT password                           |

💡 **Tip:**
Make sure the MQTT username and password match those you configured in Home Assistant’s **Mosquitto broker**.
If you’re using the built-in broker (`core-mosquitto`), you can create users in the add-on configuration.

---

#HA Installation

1. In Home Assistant, open **Settings → Add-ons → Add-on Store**
2. Click the three-dot menu (⋮) → **Repositories**
3. Add this URL:

   ```
   https://github.com/dropqube/ecowitt_mqtt_addon
   ```
4. Search for **Ecowitt MQTT Bridge Add-on** and click **Install**
5. Configure the add-on (see below) and **Start** it – I **recommend activating the "use_local_api"** option if you have multiple devices and they don't initially show up.
6. You might have to wait for a new polling interval before devices appear – you can find them in the MQTT integration.
7. If nothing appears, try saving the configuration and click **Rebuild** in the add-on, then start it again.

---

## ⚙️ Configuration (via UI)

All configuration can be done directly in Home Assistant — no YAML required.

| Option               | Description                                                                                                                | Default          |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| `broker`             | MQTT broker hostname (e.g. `core-mosquitto`)                                                                               | `core-mosquitto` |
| `port`               | MQTT port                                                                                                                  | `1883`           |
| `username`           | MQTT username *(optional)* – **Hint:** If nothing works, add your MQTT user or just create a new one (e.g. `ecowitt_mqtt`) |                  |
| `password`           | MQTT password                                                                                                              | *(optional)*     |
| `in_topic`           | Topic to subscribe to (Ecowitt publishes here)                                                                             | `ecowitt/#`      |
| `discovery_prefix`   | MQTT Discovery prefix                                                                                                      | `homeassistant`  |
| `state_prefix`       | State topic prefix                                                                                                         | `ecowitt_ha`     |
| `client_id`          | MQTT client ID                                                                                                             | `ecowitt-bridge` |
| `cleanup`            | Remove old discovery topics before publishing                                                                              | `false`          |
| `use_local_api`      | Enable direct LAN API polling                                                                                              | `false`          |
| `gateway_base_url`   | Base URL of Ecowitt gateway                                                                                                | *(optional)*     |
| `lan_timeout`        | Timeout for LAN API requests                                                                                               | `3.0`            |
| `map_refresh_sec`    | Refresh interval for LAN mapping                                                                                           | `600`            |
| `publish_lan_common` | Publish `common_list` from LAN API                                                                                         | `false`          |



---

## 🧠 How It Works

1. The bridge subscribes to the Ecowitt MQTT topic (`ecowitt/#`)
2. Each incoming message is parsed and translated into HA discovery topics
3. If LAN API polling is enabled, additional data is fetched periodically
4. Sensors appear automatically in Home Assistant with correct names and units

---

## 🛠️ Technical Notes

* Written in Python 3 (see `ecowitt_mqtt_bridge.py`)
* Add-on runs in its own container (see `Dockerfile`)
* All runtime options are read from `/data/options.json`
* Supports `amd64`, `aarch64`, and `armv7` architectures
* Uses the standard MQTT and HTTP libraries built into Python

---

## 🪴 License

This project is licensed under the **MIT License**.
See the `LICENSE` file for details.
