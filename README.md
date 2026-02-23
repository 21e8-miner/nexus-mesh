# Nexus Mesh Bridge

**The World's First Unified Cross-Spectrum Mesh Transceiver Topology.**

Nexus Mesh dynamically bridges incompatible hardware ecosystems (Reticulum Network Stack and Meshtastic) by acting as a physical multi-band gateway. It leverages a modern asynchronous Python backend (FastAPI/WebSockets) and a dynamic Leaflet-based Holographic UI to seamlessly route data, identity, and messages across both protocols in real-time.

---

## 🚀 Real-World Breakthroughs
At the hardware layer, Reticulum (RNS) and Meshtastic utilize completely different LoRa packet framing constructs. By default, they **cannot talk to each other** despite functioning in the same physical 915MHz spectrum. 

Nexus acts as a **"Middle-Out" Hardware Translator**:
1. **True Off-Grid Topography**: Nexus passively listens to `POSITION` and `NODEINFO` packets over the actual RF interface, storing them securely in an embedded SQLite DB. It dynamically live-maps these nodes even if the machine completely loses internet.
2. **Omni-Cast Architecture**: When a message comes across the Meshtastic spectrum, the engine captures the payload, restructures it into a cryptographically secure `LXMF` (Lightweight Extensible Message Format) object, and physically bounces it out over the Reticulum mesh.
3. **Disaster Resiliency**: Designed to be permanently deployed on a Raspberry Pi tied to a rooftop antenna, acting as an automated neighborhood bridge between consumer Meshtastic appliances and deep-web RNS infrastructure.
4. **Desktop Intelligence**: Integrated web OS push notifications immediately alert the operator to arriving packet bursts when the UI is minimized.

---

## 🛠 Supported Hardware

You will need **TWO** physical LoRa devices plugged into your computer via USB (or BLE) to run the bridge locally:
1. **Reticulum Node (RNode)**: Flashed via `rnodeconf` (e.g., Heltec V4, t-beam).
2. **Meshtastic Gateway**: Running standard Meshtastic firmware.

## 📦 Zero-Click Raspberry Pi / Linux Deploy
We provided a headless OS daemon install script that automatically configures venv environments and mounts an active `systemd` worker for infinite reliability across reboots.

```bash
curl -sSL https://raw.githubusercontent.com/21e8-miner/nexus-mesh/main/install-linux.sh | bash
```

## 💻 Manual Developer Installation (Mac/Linux/Windows)

Clone the repository and install the dependencies:

```bash
git clone https://github.com/21e8-miner/nexus-mesh.git
cd nexus-mesh

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Core Engine
pip install -r requirements.txt
```

*(Note: If you run into issues on macOS with AutoInterface crashes, disable AutoInterface in `~/.reticulum/config`)*

### Running the Gateway

Simply spin up the gateway using the ASGI engine.

```bash
uvicorn main:app --host 0.0.0.0 --port 8089 
```

Navigate to `http://localhost:8089` in any browser.

### Bridging Interfaces via UI
1. Head to the **System Configuration** tab.
2. Select your RNode USB Interface from the dropdown (automatically populated via active USB sniffing).
3. Select the physical path for your Meshtastic radio.
4. Toggle **Enable Omni-Cast Bridge** to activate the cross-spectrum loop.
5. Click **Apply Core Configuration**.

## 🧬 Architecture Pipeline
- **Frontend**: Vanilla Javascript + raw HTML/CSS (Zero bloat). Leaflet JS for GIS/Map rendering.
- **Backend / DB**: FastAPI + Uvicorn for asynchronous WebSocket duplexing. Integrated thread-safe SQLite3.
- **Transport**: PyMesh API / `meshtastic-python` + `Reticulum` (`RNS`/`LXMF`).
- **Data Flow**: `Meshtastic Payload (LoRa) -> Python Intercept -> LXMF Wrap -> Reticulum Transport (LoRa)`
