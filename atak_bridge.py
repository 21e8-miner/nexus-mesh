import RNS
import socket
import struct
import zlib
import time
import uuid
import sys
import threading
import os

# ATAK Standard Multicast parameters
MCAST_GRP = '239.2.3.1'
MCAST_PORT = 6969
MULTICAST_TTL = 3

# Reticulum MTU safety margin (Max ~500 bytes for RNS packets on standard links)
RNS_MTU_SAFE = 380

# Cache for packet reassembly
frag_cache = {}

class ATAKBridge:
    def __init__(self):
        # 1. Initialize Reticulum
        self.reticulum = RNS.Reticulum()
        
        # 2. Persist Identity
        if os.path.exists("atak_identity"):
            self.identity = RNS.Identity.from_file("atak_identity")
        else:
            self.identity = RNS.Identity()
            self.identity.to_file("atak_identity")
            
        # 3. Create a PLAIN destination to broadcast out to the mesh
        # Any node listening on "nexus", "atak" will receive these packets
        self.bcast_identity = RNS.Identity()
        self.bcast_destination = RNS.Destination(self.bcast_identity, RNS.Destination.OUT, RNS.Destination.PLAIN, "nexus", "atak")
        
        # 4. Create an IN destination to listen for incoming mesh ATAK packets
        self.listen_destination = RNS.Destination(self.identity, RNS.Destination.IN, RNS.Destination.PLAIN, "nexus", "atak")
        self.listen_destination.set_packet_callback(self.receive_rns)

        # 5. Setup Local Multicast Socket (Receive from ATAK App)
        self.sock_in = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock_in.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock_in.bind(('', MCAST_PORT))
        
        mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
        self.sock_in.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        # 6. Setup Local Multicast Socket (Send to ATAK App)
        self.sock_out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock_out.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)

        self.last_sent_hashes = []
        self.lock = threading.Lock()

    def clean_cache(self):
        # Prune fragments older than 60 seconds
        now = time.time()
        with self.lock:
            stale_keys = [k for k, v in frag_cache.items() if now - v["time"] > 60]
            for k in stale_keys:
                del frag_cache[k]

    def receive_rns(self, rns_packet, receipt):
        payload = rns_packet.data
        if not payload:
            return
            
        try:
            # Simple fragmentation protocol:
            # 16-byte UUID (msg_id) | 2-byte total_frags | 2-byte frag_idx | data
            if len(payload) < 20: 
                return
            
            msg_id = payload[:16]
            total_frags = struct.unpack(">H", payload[16:18])[0]
            frag_idx = struct.unpack(">H", payload[18:20])[0]
            data = payload[20:]
            
            with self.lock:
                if msg_id not in frag_cache:
                    frag_cache[msg_id] = {
                        "time": time.time(),
                        "total": total_frags,
                        "parts": {}
                    }
                
                frag_cache[msg_id]["parts"][frag_idx] = data
                
                # Check if complete
                if len(frag_cache[msg_id]["parts"]) == total_frags:
                    assembled = b"".join([frag_cache[msg_id]["parts"][i] for i in range(total_frags)])
                    del frag_cache[msg_id]
                    
                    # Decompress
                    xml_data = zlib.decompress(assembled)
                    
                    # Hash it to prevent loopback when we rebroadcast on multicast
                    xml_hash = hash(xml_data)
                    self.last_sent_hashes.append(xml_hash)
                    if len(self.last_sent_hashes) > 100:
                        self.last_sent_hashes.pop(0)
                        
                    print(f"[ATAK Bridge] Received & Reassembled {total_frags} RNS frags -> {len(xml_data)} byte CoT.")
                    
                    # Broadcast to local UDP ATAK clients
                    self.sock_out.sendto(xml_data, (MCAST_GRP, MCAST_PORT))
                
        except Exception as e:
            print(f"[ATAK Bridge] RNS Reassembly Error: {e}")

    def start(self):
        print(f"Nexus ATAK Bridge -> Listening on Local Multicast {MCAST_GRP}:{MCAST_PORT} & Reticulum Mesh")
        
        while True:
            try:
                data, addr = self.sock_in.recvfrom(65535)
                
                # Periodically clean broken fragments
                self.clean_cache()

                # Ignore loopbacks from our own UDP rebroadcasts
                xml_hash = hash(data)
                if xml_hash in self.last_sent_hashes:
                    continue
                
                # Prevent looping
                with self.lock:
                    self.last_sent_hashes.append(xml_hash)
                    if len(self.last_sent_hashes) > 100:
                        self.last_sent_hashes.pop(0)
                    
                compressed = zlib.compress(data)
                msg_id = uuid.uuid4().bytes
                
                # Chunk payload mathematically to respect RNS MTU limits
                chunks = [compressed[i:i + RNS_MTU_SAFE] for i in range(0, len(compressed), RNS_MTU_SAFE)]
                total_frags = len(chunks)
                
                for i, chunk in enumerate(chunks):
                    header = msg_id + struct.pack(">H", total_frags) + struct.pack(">H", i)
                    packet_data = header + chunk
                    
                    # Distribute across the RF interfaces natively using Reticulum
                    rns_pkt = RNS.Packet(self.bcast_destination, packet_data)
                    rns_pkt.send()
                    
                    # Tiny hardware pause so we don't saturate strict physical LoRa/HaLow duty channels
                    time.sleep(0.08) 
                
                print(f"[ATAK Bridge] Bridged native {len(data)} byte CoT -> {len(compressed)} compressed bytes in {total_frags} RNS fragments.")

            except Exception as e:
                print(f"[ATAK Bridge] Main Loop Error: {e}")
                time.sleep(1)

if __name__ == "__main__":
    bridge = ATAKBridge()
    bridge.start()
