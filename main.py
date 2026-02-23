import asyncio
import json
import logging
import threading
import time
import RNS
import LXMF
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import sqlite3
import urllib.request
import serial.tools.list_ports
import meshtastic
import meshtastic.serial_interface
from pubsub import pub

# Initialize DB
def init_db():
    conn = sqlite3.connect('nexus.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  network TEXT,
                  sender TEXT,
                  content TEXT,
                  timestamp INTEGER,
                  dest_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS local_nodes
                 (id TEXT PRIMARY KEY,
                  name TEXT,
                  hw TEXT,
                  lat REAL,
                  lon REAL,
                  last_heard INTEGER)''')
    conn.commit()
    conn.close()

init_db()

def save_message_sync(msg):
    conn = sqlite3.connect('nexus.db')
    c = conn.cursor()
    c.execute('INSERT INTO messages (network, sender, content, timestamp, dest_id) VALUES (?, ?, ?, ?, ?)',
              (msg.get('network', 'Local'), msg.get('sender', ''), msg.get('content', ''), int(msg.get('timestamp', time.time())), msg.get('dest_id', '')))
    conn.commit()
    conn.close()

def save_node(node_id, name="Unknown", hw="Unknown", lat=None, lon=None):
    conn = sqlite3.connect('nexus.db')
    c = conn.cursor()
    c.execute('''INSERT INTO local_nodes (id, name, hw, lat, lon, last_heard) 
                 VALUES (?, ?, ?, ?, ?, ?)
                 ON CONFLICT(id) DO UPDATE SET 
                 name=COALESCE(?, name), 
                 hw=COALESCE(?, hw), 
                 lat=COALESCE(?, lat), 
                 lon=COALESCE(?, lon), 
                 last_heard=?''', 
              (node_id, name, hw, lat, lon, int(time.time()), name, hw, lat, lon, int(time.time())))
    conn.commit()
    conn.close()

def get_local_nodes():
    conn = sqlite3.connect('nexus.db')
    c = conn.cursor()
    c.execute('SELECT id, name, hw, lat, lon FROM local_nodes WHERE lat IS NOT NULL AND lon IS NOT NULL')
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'name': r[1], 'hw': r[2], 'lat': r[3], 'lon': r[4], 'off_grid': True} for r in rows]

async def save_message(msg):
    await asyncio.to_thread(save_message_sync, msg)

def get_history_sync():
    conn = sqlite3.connect('nexus.db')
    c = conn.cursor()
    c.execute('SELECT network, sender, content, timestamp, dest_id FROM messages ORDER BY timestamp ASC LIMIT 500')
    rows = c.fetchall()
    conn.close()
    return [{'network': r[0], 'sender': r[1], 'content': r[2], 'timestamp': r[3], 'dest_id': r[4]} for r in rows]

async def get_history():
    return await asyncio.to_thread(get_history_sync)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NexusChat")

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory unified message bus
class MessageBus:
    def __init__(self):
        self.active_connections = []
        
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")
        
        # Send history on connect
        history = await get_history()
        for msg in history:
            await websocket.send_text(json.dumps(msg))
        
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Client disconnected. Total: {len(self.active_connections)}")
            
    async def broadcast(self, message: dict):
        if message.get('sender') != 'Me':  # Only save incoming to avoid duplicates of Me
            await save_message(message)
            
        text = json.dumps(message)
        for connection in self.active_connections:
            try:
                await connection.send_text(text)
            except Exception as e:
                logger.error(f"Error broadcasting: {e}")

bus = MessageBus()

# Reticulum & LXMF Integration
# Global State
lxmf_router = None
lxmf_identity = None
meshtastic_interface = None
bridge_lock = threading.Lock()
bridge_config = {
    "omni_cast": False,
    "rnode_port": "/dev/cu.usbmodem101",
    "mesh_port": ""
}
main_loop = None

def init_reticulum():
    global lxmf_router, lxmf_identity
    logger.info("Initializing Reticulum...")
    try:
        # Starting Reticulum locally
        reticulum = RNS.Reticulum()
        # Create or load an identity
        import os
        if os.path.exists("nexus_identity"):
            lxmf_identity = RNS.Identity.from_file("nexus_identity")
        else:
            lxmf_identity = RNS.Identity()
            lxmf_identity.to_file("nexus_identity")
        # Create an LXMF Router
        lxmf_router = LXMF.LXMRouter(identity=lxmf_identity, storagepath="/tmp/nexus_lxmf")
        lxmf_router.register_delivery_callback(lxmf_delivery_callback)
        logger.info(f"Reticulum ready. LXMF Hash: {RNS.prettyhexrep(lxmf_identity.hash)}")
    except Exception as e:

        logger.error(f"Failed to init Reticulum: {e}")

def lxmf_delivery_callback(message):
    logger.info(f"Received LXMF message from {RNS.prettyhexrep(message.source_hash)}")
    msg_data = {
        "network": "Reticulum",
        "sender": RNS.prettyhexrep(message.source_hash),
        "content": message.content.decode('utf-8') if isinstance(message.content, bytes) else message.content,
        "timestamp": message.timestamp
    }
    # We must broadcast to websockets from the async loop safely
    if main_loop and main_loop.is_running():
        main_loop.call_soon_threadsafe(asyncio.create_task, bus.broadcast(msg_data))
        
    # If Omni-Cast Bridge is enabled, we automatically cross-post this to Meshtastic
    with bridge_lock:
        omni_cast = bridge_config.get("omni_cast")
    if omni_cast and meshtastic_interface:
        logger.info("[OMNI-CAST] Re-broadcasting LXMF receive out to Meshtastic LORA")
        try:
            meshtastic_interface.sendText(f"[Bridge] {msg_data['content']}")
        except Exception as e:
            logger.error(f"Meshtastic cross-post failed: {e}")

def on_meshtastic_receive(packet, interface):
    try:
        if 'decoded' in packet and packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
            text = packet['decoded']['payload'].decode('utf-8')
            logger.info(f"Received Meshtastic message: {text}")
            
            msg_data = {
                "network": "Meshtastic",
                "sender": packet.get('fromId', 'Unknown'),
                "content": text,
                "timestamp": int(time.time())
            }
            if main_loop and main_loop.is_running():
                main_loop.call_soon_threadsafe(asyncio.create_task, bus.broadcast(msg_data))
                
            # Cross-post to Reticulum if Bridge is active
            with bridge_lock:
                omni_cast = bridge_config.get("omni_cast")
            if omni_cast and lxmf_router:
                logger.info("[OMNI-CAST] Re-broadcasting Meshtastic receive to Reticulum LXMF")
                try:
                    prop_destination = RNS.Destination(None, RNS.Destination.OUT, RNS.Destination.PLAIN, "nexus", "omnicast")
                    src_destination = RNS.Destination(lxmf_identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "nexus", "bridge")
                    bridge_msg = f"[Bridged from Meshtastic Node {msg_data['sender']}]: {text}"
                    message = LXMF.LXMessage(prop_destination, src_destination, bridge_msg, title="Nexus Bridge", desired_method=LXMF.LXMessage.DIRECT)
                    lxmf_router.handle_outbound(message)
                except Exception as e:
                    logger.error(f"Failed to bridge Meshtastic to Reticulum: {e}")
                
    except Exception as e:
        logger.error(f"Meshtastic handler error: {e}")

def on_meshtastic_position(packet, interface):
    try:
        from_id = packet.get('fromId', 'Unknown')
        if 'decoded' in packet and 'position' in packet['decoded']:
            pos = packet['decoded']['position']
            lat = pos.get('latitude', 0) / 10000000.0 if pos.get('latitude') else None
            lon = pos.get('longitude', 0) / 10000000.0 if pos.get('longitude') else None
            if lat and lon:
                save_node(node_id=from_id, lat=lat, lon=lon)
                logger.debug(f"Offline GPS Sync: Updated position for node {from_id}")
    except Exception as e:
        logger.error(f"Meshtastic position error: {e}")

def on_meshtastic_nodeinfo(packet, interface):
    try:
        from_id = packet.get('fromId', 'Unknown')
        if 'decoded' in packet and 'user' in packet['decoded']:
            user = packet['decoded']['user']
            name = user.get('longName', 'Unknown')
            hw = user.get('hwModel', 'Unknown')
            save_node(node_id=from_id, name=name, hw=hw)
            logger.debug(f"Offline NodeInfo Sync: Updated specs for node {from_id}")
    except Exception as e:
        logger.error(f"Meshtastic nodeinfo error: {e}")

pub.subscribe(on_meshtastic_receive, "meshtastic.receive.text")
pub.subscribe(on_meshtastic_position, "meshtastic.receive.position")
pub.subscribe(on_meshtastic_nodeinfo, "meshtastic.receive.user")

def connect_meshtastic():
    global meshtastic_interface
    with bridge_lock:
        port = bridge_config.get("mesh_port")
    if not port:
        logger.info("Meshtastic: No port configured.")
        return
        
    logger.info(f"Connecting to Meshtastic on {port}...")
    try:
        if meshtastic_interface:
            try:
                meshtastic_interface.close()
            except Exception:
                pass
        meshtastic_interface = meshtastic.serial_interface.SerialInterface(devPath=port)
        logger.info("Meshtastic connected!")
    except Exception as e:
        logger.error(f"Meshtastic connection failed: {e}")

def _fetch_liam_nodes():
    req = urllib.request.Request('https://meshtastic.liamcottle.net/api/v1/nodes', headers={'User-Agent': 'Nexus-Mesh'})
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode('utf-8'))

async def sync_mesh_nodes():
    while True:
        logger.info("Syncing Mesh telemetry from Liam Cottle API...")
        nodes = []
        try:
            data = await asyncio.to_thread(_fetch_liam_nodes)
            for node in data.get('nodes', []):
                lat = node.get('latitude')
                lon = node.get('longitude')
                if lat and lon:
                    flat = lat / 10000000.0
                    flon = lon / 10000000.0
                    nodes.append({
                        'id': node.get('node_id_hex', 'Unknown'),
                        'name': node.get('long_name', 'Unknown'),
                        'hw': node.get('hardware_model_name', 'Unknown'),
                        'lat': flat,
                        'lon': flon,
                        'off_grid': False
                    })
        except Exception as e:
            logger.error(f"Failed to sync telemetry from cloud API: {e}")
            
        try:
            # Always Merge Offline Heard Nodes regardless of Cloud API status
            local_nodes = await asyncio.to_thread(get_local_nodes)
            local_ids = {n['id'] for n in local_nodes}
            merged_nodes = [n for n in nodes if n['id'] not in local_ids] + local_nodes
            
            with open('static/mesh_nodes.json', 'w') as f:
                json.dump(merged_nodes[:5000], f)
            logger.info(f"Successfully synced {len(merged_nodes[:5000])} combined online/offline topology nodes.")
        except Exception as e:
            logger.error(f"Failed to process offline topography: {e}")
            
        await asyncio.sleep(900)  # Sync every 15 mins

@app.on_event("startup")
async def startup_event():
    # Store reference to main loop
    global main_loop
    main_loop = asyncio.get_running_loop()
    
    # Start map scraper loop
    asyncio.create_task(sync_mesh_nodes())
    
    # Run Reticulum init in main thread since it requires signal handlers
    init_reticulum()
    # Placeholder for Meshtastic init
    logger.info("Meshtastic integration ready for connection.")


@app.get("/api/local_nodes")
async def get_local_nodes_api():
    return await asyncio.to_thread(get_local_nodes)

@app.get("/api/usb_ports")
def get_usb_ports():
    ports = serial.tools.list_ports.comports()
    return [{"device": p.device, "description": p.description} for p in ports]

@app.get("/api/config")
def get_config():
    with bridge_lock:
        return dict(bridge_config)

@app.get("/")
async def get():
    def read_index():
        with open("static/index.html") as f:
            return f.read()
    html_content = await asyncio.to_thread(read_index)
    return HTMLResponse(html_content)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await bus.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            logger.info(f"Received from UI: {msg}")
            if msg.get("type") == "config":
                needs_reconnect = False
                with bridge_lock:
                    bridge_config["omni_cast"] = msg.get("omni_cast", False)
                    bridge_config["rnode_port"] = msg.get("rnode_port", "")
                    
                    new_mesh_port = msg.get("mesh_port", "")
                    if new_mesh_port != bridge_config["mesh_port"]:
                        needs_reconnect = True
                        bridge_config["mesh_port"] = new_mesh_port
                
                if needs_reconnect:
                    t = threading.Thread(target=connect_meshtastic, daemon=True)
                    t.start()
                    
                logger.info(f"Updated System Config: {bridge_config}")
                continue
                
            network = msg.get("network", "")
            content = msg.get("content", "")
            dest_id = msg.get("dest_id", "")

            # Send message back to UI immediately as ack and save to DB
            ack_msg = {
                "network": msg.get("network", "Local"),
                "sender": "Me",
                "content": msg.get("content", ""),
                "timestamp": int(time.time()),
                "dest_id": dest_id
            }
            await save_message(ack_msg)
            await bus.broadcast(ack_msg)
            
            # Omni-Cast / Reticulum
            if (network in ["Reticulum", "Omni-Cast"]) and lxmf_router:
                logger.info(f"Routing out via Reticulum: {content}")
                try:
                    # In a true decentralized mesh, you need a destination hash. 
                    # For a local UI Omni-Cast demo, we broadcast it out over the propagation channel
                    # Setting up a generic propagation delivery for UI tests
                    prop_destination = RNS.Destination(None, RNS.Destination.OUT, RNS.Destination.PLAIN, "nexus", "omnicast")
                    src_destination = RNS.Destination(lxmf_identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "nexus", "bridge")
                    message = LXMF.LXMessage(prop_destination, src_destination, content, title="Nexus Bridge", desired_method=LXMF.LXMessage.DIRECT)
                    lxmf_router.handle_outbound(message)
                except Exception as e:
                    logger.error(f"LXMF Send Error: {e}")
                
            # Omni-Cast / Meshtastic
            if (network in ["Meshtastic", "Omni-Cast"]) and meshtastic_interface:
                if dest_id and dest_id != "":
                    logger.info(f"Routing out via Meshtastic to specific node {dest_id}: {content}")
                    try:
                        meshtastic_interface.sendText(content, destinationId=dest_id)
                    except Exception as e:
                        logger.error(f"Meshtastic send error: {e}")
                else:
                    logger.info(f"Routing out via Meshtastic (Broadcast): {content}")
                    try:
                        meshtastic_interface.sendText(content)
                    except Exception as e:
                        logger.error(f"Meshtastic send error: {e}")
                        
            # ATAK Pass-Through UI Update
            if network == "ATAK":
                logger.info(f"UI submitted ATAK Cursor-on-Target telemetry via WebSocket logic")
                # In full production, this would bind directly to the local ATAK multicast UDP sock
                # and emit the payload. For the scope of the Chat interface, we just log it natively.
                
    except WebSocketDisconnect:
        bus.disconnect(websocket)
