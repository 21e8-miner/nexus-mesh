import asyncio
import json
import logging
import threading
import time
import RNS
import logging
import threading
import RNS
import LXMF
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import meshtastic
import meshtastic.serial_interface
from pubsub import pub

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
        
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Client disconnected. Total: {len(self.active_connections)}")
            
    async def broadcast(self, message: dict):
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
bridge_config = {
    "omni_cast": False,
    "rnode_port": "/dev/cu.usbmodem101",
    "mesh_port": ""
}

def init_reticulum():
    global lxmf_router, lxmf_identity
    logger.info("Initializing Reticulum...")
    try:
        # Starting Reticulum locally
        reticulum = RNS.Reticulum()
        # Create an identity
        lxmf_identity = RNS.Identity()
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
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(bus.broadcast(msg_data))
        
    # If Omni-Cast Bridge is enabled, we automatically cross-post this to Meshtastic
    if bridge_config["omni_cast"] and meshtastic_interface:
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
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(bus.broadcast(msg_data))
                
            # Cross-post to Reticulum if Bridge is active
            if bridge_config["omni_cast"] and lxmf_router:
                logger.info("[OMNI-CAST] Re-broadcasting Meshtastic receive to Reticulum LXMF")
                try:
                    prop_destination = RNS.Destination(lxmf_identity, RNS.Destination.OUT, RNS.Destination.PLAIN, "nexus", "omnicast")
                    bridge_msg = f"[Bridged from Meshtastic Node {msg_data['sender']}]: {text}"
                    message = LXMF.LXMessage(prop_destination, lxmf_router.identity, bridge_msg, title="Nexus Bridge", desired_method=LXMF.LXMessage.DIRECT)
                    lxmf_router.handle_outbound(message)
                except Exception as e:
                    logger.error(f"Failed to bridge Meshtastic to Reticulum: {e}")
                
    except Exception as e:
        logger.error(f"Meshtastic handler error: {e}")

pub.subscribe(on_meshtastic_receive, "meshtastic.receive.text")

def connect_meshtastic():
    global meshtastic_interface
    port = bridge_config["mesh_port"]
    if not port:
        logger.info("Meshtastic: No port configured.")
        return
        
    logger.info(f"Connecting to Meshtastic on {port}...")
    try:
        meshtastic_interface = meshtastic.serial_interface.SerialInterface(devPath=port)
        logger.info("Meshtastic connected!")
    except Exception as e:
        logger.error(f"Meshtastic connection failed: {e}")

@app.on_event("startup")
async def startup_event():
    # Run Reticulum init in main thread since it requires signal handlers
    init_reticulum()
    # Placeholder for Meshtastic init
    logger.info("Meshtastic integration ready for connection.")


@app.get("/")
async def get():
    with open("static/index.html") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await bus.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            logger.info(f"Received from UI: {msg}")
            if msg.get("type") == "config":
                bridge_config["omni_cast"] = msg.get("omni_cast", False)
                bridge_config["rnode_port"] = msg.get("rnode_port", "")
                
                new_mesh_port = msg.get("mesh_port", "")
                if new_mesh_port != bridge_config["mesh_port"]:
                    bridge_config["mesh_port"] = new_mesh_port
                    t = threading.Thread(target=connect_meshtastic, daemon=True)
                    t.start()
                    
                logger.info(f"Updated System Config: {bridge_config}")
                continue
                
            # Send message back to UI immediately as ack
            await bus.broadcast({
                "network": msg.get("network", "Local"),
                "sender": "Me",
                "content": msg.get("content", ""),
                "timestamp": int(time.time())
            })
            
            network = msg.get("network", "")
            content = msg.get("content", "")
            dest_id = msg.get("dest_id", "")
            
            # Omni-Cast / Reticulum
            if (network in ["Reticulum", "Omni-Cast"]) and lxmf_router:
                logger.info(f"Routing out via Reticulum: {content}")
                try:
                    # In a true decentralized mesh, you need a destination hash. 
                    # For a local UI Omni-Cast demo, we broadcast it out over the propagation channel
                    # Setting up a generic propagation delivery for UI tests
                    prop_destination = RNS.Destination(lxmf_identity, RNS.Destination.OUT, RNS.Destination.PLAIN, "nexus", "omnicast")
                    message = LXMF.LXMessage(prop_destination, lxmf_router.identity, content, title="Nexus Bridge", desired_method=LXMF.LXMessage.DIRECT)
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
                
    except WebSocketDisconnect:
        bus.disconnect(websocket)
