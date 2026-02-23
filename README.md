# Nexus Mesh Bridge

**The World's First Unified Cross-Spectrum Mesh Transceiver Topology.**

Nexus Mesh dynamically bridges incompatible hardware ecosystems (Reticulum Network Stack and Meshtastic) by acting as a physical multi-band gateway. It leverages a modern asynchronous Python backend (FastAPI/WebSockets) and a dynamic Leaflet-based Holographic UI to seamlessly route data, identity, and messages across both protocols in real-time.

---

## 🚀 Real-World Usefulness
At the hardware layer, Reticulum (RNS) and Meshtastic utilize completely different LoRa packet framing constructs. By default, they **cannot talk to each other** despite functioning in the same physical 915MHz spectrum. 

Nexus acts as a **"Middle-Out" Hardware Translator**:
1. **Disaster Resiliency**: Deployed on a Raspberry Pi or Desktop hooked up to both types of radios (e.g. Heltec V4 + T-Beam), Nexus listens to both networks simultaneously.
2. **Omni-Cast Architecture**: When a message comes across the Meshtastic spectrum, the engine captures the payload, restructures it into a cryptographically secure `LXMF` (Lightweight Extensible Message Format) object, and physically bounces it out over the Reticulum mesh.
3. **Cross-Community Unity**: Hardcore privacy advocates running Reticulum can natively converse with standard consumer Meshtastic users completely transparently.
4. **Targeted Topography Insights**: Aggregates the public Meshtastic MQTT heartbeat metrics to live-map thousands of local endpoints right onto your local dashboard for real-time situational awareness.

---

## 🛠 Prerequisites

You will need **TWO** physical LoRa devices plugged into your computer via USB (or BLE) to run the bridge locally:
1. **Reticulum Node (RNode)**: Flashed via `rnodeconf` (e.g., Heltec V4).
2. **Meshtastic Gateway**: Running standard Meshtastic firmware.

## 📦 Installation

Clone the repository and install the dependencies:

```bash
git clone https://github.com/yourusername/nexus-mesh.git
cd nexus-mesh

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Core Engine
pip install -r requirements.txt
```

*(Note: If you run into issues on macOS with AutoInterface crashes, disable AutoInterface in `~/.reticulum/config`)*

## ⚡️ Running the Gateway

Simply spin up the gateway using the ASGI engine.

```bash
uvicorn main:app --host 0.0.0.0 --port 8089 
```

Navigate to `http://localhost:8089` in any browser.

### Bridging Interfaces
1. Head to the **System Settings** tab.
2. Ensure your RNode USB path is accurate (e.g. `/dev/cu.usbmodem101`).
3. Enter the interface path for your Meshtastic radio.
4. Toggle **Enable Omni-Cast Bridge** to activate the cross-spectrum loop.
5. Click **Apply Core Configuration**.

## 🧬 Architecture Pipeline
- **Frontend**: Vanilla Javascript + raw HTML/CSS (Zero bloat). Leaflet JS for GIS/Map rendering.
- **Backend**: FastAPI + Uvicorn for asynchronous WebSocket duplexing.
- **Transport**: PyMesh API / `meshtastic-python` + `Reticulum` (`RNS`/`LXMF`).
- **Data Flow**: `Meshtastic Payload (LoRa) -> Python Intercept -> LXMF Wrap -> Reticulum Transport (LoRa)`
