import json

with open('liam.json', 'r') as f:
    data = json.load(f)

nodes = []
nodes_list = data.get('nodes', [])
for node in nodes_list:
    lat = node.get('latitude')
    lon = node.get('longitude')
    if lat and lon:
        flat = lat / 10000000.0
        flon = lon / 10000000.0
        
        # USA rough bounds
        if -130 < flon < -60 and 20 < flat < 55:
            nodes.append({
                'id': node.get('node_id_hex', 'Unknown'),
                'name': node.get('long_name', 'Unknown'),
                'hw': node.get('hardware_model_name', 'Unknown'),
                'lat': flat,
                'lon': flon
            })

with open('static/mesh_nodes.json', 'w') as f:
    json.dump(nodes[:5000], f)

print(f"Parsed {len(nodes[:5000])} US nodes.")
