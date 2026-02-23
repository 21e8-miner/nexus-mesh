const chatHistory = document.getElementById('chat-history');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const networkSelect = document.getElementById('network-select');
const viewTitle = document.getElementById('view-title');

const mapContainer = document.getElementById('map-container');
const nodesContainer = document.getElementById('nodes-container');
const composer = document.getElementById('composer');

// Nav items
const navChat = document.getElementById('nav-chat');
const navMap = document.getElementById('nav-map');
const navNodes = document.getElementById('nav-nodes');

let map = null;

// Establish WebSocket Connection
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${protocol}//${window.location.host}/ws`;
let ws;

function connectWS() {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        addSystemMessage("Uplink Established.");
        if (Notification.permission !== 'granted' && Notification.permission !== 'denied') {
            Notification.requestPermission();
        }
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        addMessage(data);

        if (data.sender !== 'Me' && document.hidden) {
            if (Notification.permission === "granted") {
                new Notification(`nexus: ${data.network}`, {
                    body: `${data.sender}: ${data.content}`,
                    icon: '/static/favicon.ico' // Ensure an icon exists or it degrades gracefully
                });
            }
        }
    };

    ws.onclose = () => {
        addSystemMessage("Uplink Lost. Retrying...");
        setTimeout(connectWS, 3000);
    };
}

function formatTime(timestamp) {
    const d = timestamp ? new Date(timestamp * 1000) : new Date();
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function addSystemMessage(text) {
    const div = document.createElement('div');
    div.className = 'message system';
    div.innerHTML = `<div class="content">${text}</div>`;
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function addMessage(msg) {
    const isOutgoing = msg.sender === "Me";
    const div = document.createElement('div');
    div.className = `message ${isOutgoing ? 'outgoing' : 'incoming'}`;

    const netClass = msg.network ? msg.network.toLowerCase() : 'local';

    div.innerHTML = `
        <div class="msg-meta">
            ${isOutgoing ? '' : `<span>${msg.sender.substring(0, 8)}...</span>`}
            <span class="net-badge ${netClass}">${msg.network || 'Local'}</span>
            <span>${formatTime(msg.timestamp)}</span>
        </div>
        <div class="content">${msg.content}</div>
    `;

    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function sendMessage() {
    const text = messageInput.value.trim();
    if (!text) return;

    const network = networkSelect.value;
    const destIdInput = document.getElementById('dest-id-input');
    const destId = destIdInput ? destIdInput.value.trim() : "";

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            network: network,
            content: text,
            dest_id: destId
        }));
        messageInput.value = '';
    } else {
        addSystemMessage("Cannot transmit. Uplink is down.");
    }
}

// Global scope function for the map popup button
window.targetNode = function (id) {
    document.getElementById('dest-id-input').value = id;
    document.getElementById('network-select').value = "Meshtastic";
    switchView('chat');
    document.getElementById('message-input').focus();
};

sendBtn.addEventListener('click', sendMessage);
messageInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
});

function initMap() {
    if (map) return; // already initialized
    // Define Dark Matter map style matching the aesthetic
    map = L.map('map-container').setView([40.8482, -73.9976], 11);

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 20
    }).addTo(map);

    // Fetch Real Live Mesh Nodes
    fetch('/static/mesh_nodes.json')
        .then(res => res.json())
        .then(nodes => {
            nodes.forEach(node => {
                L.circleMarker([node.lat, node.lon], {
                    color: '#12C2E9',
                    fillColor: '#12C2E9',
                    fillOpacity: 0.3,
                    radius: 3,
                    weight: 1
                }).bindPopup(`<b>${node.name}</b><br>ID: ${node.id}<br>HW: ${node.hw}<br><button onclick="targetNode('${node.id}')" style="margin-top:8px; padding:4px 8px; background:var(--accent); color:black; border:none; border-radius:4px; font-weight:bold; cursor:pointer;">Target Node</button>`).addTo(map);
            });
        })
        .catch(err => console.error("Error loading mesh nodes", err));

    // Keep local node visible on top
    L.circleMarker([40.8482, -73.9976], {
        color: '#00ffcc',
        fillColor: '#00ffcc',
        fillOpacity: 0.8,
        radius: 10,
        weight: 2
    }).bindPopup("<b>RNode / 101</b><br>Heltec V4 (Reticulum L1)<br>Status: Direct Link").addTo(map);

    L.circleMarker([40.8350, -73.9700], {
        color: '#C471ED',
        fillColor: '#C471ED',
        fillOpacity: 0.8,
        radius: 10,
        weight: 2
    }).bindPopup("<b>RNode / 1101</b><br>Heltec V4 (Reticulum L1)<br>Status: Linked").addTo(map);
}

const navSettings = document.getElementById('nav-settings');
const settingsContainer = document.getElementById('settings-container');

function switchView(view) {
    [navChat, navMap, navNodes, navSettings].forEach(n => n && n.classList.remove('active'));
    chatHistory.style.display = 'none';
    mapContainer.style.display = 'none';
    nodesContainer.style.display = 'none';
    settingsContainer.style.display = 'none';
    composer.style.display = 'none';

    if (view === 'chat') {
        navChat.classList.add('active');
        viewTitle.innerText = "Unified Frequency";
        chatHistory.style.display = 'flex';
        composer.style.display = 'flex';
    } else if (view === 'map') {
        navMap.classList.add('active');
        viewTitle.innerText = "Live Mesh Topology Map";
        mapContainer.style.display = 'flex';
        initMap();
        setTimeout(() => map.invalidateSize(), 150);
    } else if (view === 'nodes') {
        navNodes.classList.add('active');
        viewTitle.innerText = "System Endpoints";
        nodesContainer.style.display = 'block';

        // Populate node view dynamically
        const meshPort = document.getElementById('mesh-port')?.value || "None configured";
        const bridgeEnabled = document.getElementById('omni-cast-toggle')?.checked ? "ACTIVE" : "Disabled";

        nodesContainer.innerHTML = `
            <div style="background: rgba(255,255,255,0.05); padding: 15px; border-radius: 10px; margin-bottom: 10px; border: 1px solid var(--border-glass);">
                <strong>Local Primary Interface</strong> - Heltec LoRa32 v4<br>
                Status: <span style="color:var(--accent);">Active</span><br>
                Spectrum: 915 MHz L1 Mesh<br>
                Hardware Path: /dev/cu.usbmodem101<br>
                Transport Protocol: Reticulum Network Stack (RNS)
            </div>
            <div style="background: rgba(255,255,255,0.05); padding: 15px; border-radius: 10px; margin-bottom: 10px; border: 1px solid var(--border-glass);">
                <strong>Secondary Carrier Node</strong> - Bridged Appliance<br>
                Status: <span style="${bridgeEnabled === 'ACTIVE' ? 'color:var(--meshtastic)' : 'color:var(--text-muted)'}">${bridgeEnabled}</span><br>
                Hardware Access: ${meshPort}<br>
                Transport Protocol: Meshtastic Serial API
            </div>
        `;

    } else if (view === 'settings') {
        navSettings.classList.add('active');
        viewTitle.innerText = "System Configuration";
        settingsContainer.style.display = 'block';

        // Auto-detect USB Ports
        fetch('/api/usb_ports')
            .then(res => res.json())
            .then(ports => {
                const datalist = document.getElementById('usb-ports');
                if (datalist) {
                    datalist.innerHTML = '';
                    ports.forEach(p => {
                        const opt = document.createElement('option');
                        opt.value = p.device;
                        opt.text = p.description;
                        datalist.appendChild(opt);
                    });
                }
            })
            .catch(err => console.error("Error auto-detecting USB ports", err));
    }
}

navChat.addEventListener('click', () => switchView('chat'));
navMap.addEventListener('click', () => switchView('map'));
navNodes.addEventListener('click', () => switchView('nodes'));
if (navSettings) navSettings.addEventListener('click', () => switchView('settings'));

// Settings config
document.getElementById('save-settings-btn')?.addEventListener('click', () => {
    const omniCast = document.getElementById('omni-cast-toggle').checked;
    const rnodePort = document.getElementById('rnode-port').value;
    const meshPort = document.getElementById('mesh-port').value;

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: "config",
            omni_cast: omniCast,
            rnode_port: rnodePort,
            mesh_port: meshPort
        }));

        let originalText = document.getElementById('save-settings-btn').innerText;
        document.getElementById('save-settings-btn').innerText = "Quantum Bridge Linked!";
        document.getElementById('save-settings-btn').style.background = "#fff";
        setTimeout(() => {
            document.getElementById('save-settings-btn').innerText = originalText;
            document.getElementById('save-settings-btn').style.background = "var(--accent)";
        }, 2000);
    }
});

// Init
connectWS();
