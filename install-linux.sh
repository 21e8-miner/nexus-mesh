#!/bin/bash
# High-Availability Deployment Script for Raspberry Pi & Debian/Ubuntu
# Nexus Mesh Bridge 

set -e

echo "🚀 Installing Nexus Mesh Core..."

# Install exact python dependencies
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip

# Create dedicated directory
DIR="/opt/nexus-mesh"
if [ ! -d "$DIR" ]; then
    sudo mkdir -p "$DIR"
    sudo chown $USER:$USER "$DIR"
fi

# Clone latest if not present
if [ ! -d "$DIR/.git" ]; then
    git clone https://github.com/21e8-miner/nexus-mesh.git "$DIR"
else
    cd "$DIR"
    git pull origin main
fi

cd "$DIR"

# Clean environment building
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create systemd daemon for automatic startup
SERVICE_PATH="/etc/systemd/system/nexus-mesh.service"
echo "Creating systemd daemon at $SERVICE_PATH..."
sudo bash -c "cat > $SERVICE_PATH" << EOF
[Unit]
Description=Nexus Mesh Bridge Daemon
After=network.target

[Service]
User=$USER
WorkingDirectory=$DIR
Environment="PATH=$DIR/venv/bin"
ExecStart=$DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8089 --log-level info
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Activate service
sudo systemctl daemon-reload
sudo systemctl enable nexus-mesh.service
sudo systemctl restart nexus-mesh.service

echo "✅ Nexus Mesh is now running! View logs with: sudo journalctl -fu nexus-mesh"
echo "Access the dashboard locally at: http://localhost:8089"
