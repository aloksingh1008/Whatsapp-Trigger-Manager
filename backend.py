#!/usr/bin/env python3
"""
Simple WhatsApp Trigger Manager Backend
- Single file Flask application
- SQLite database
- Simple trigger management
- WhatsApp webhook handling
"""

from flask import Flask, request, jsonify, render_template_string
import sqlite3
import json
import uuid
import hashlib
import os
from datetime import datetime
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Database setup
DATABASE = 'triggers.db'

def init_db():
    """Initialize the database"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Create triggers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id TEXT UNIQUE NOT NULL,
            business_name TEXT NOT NULL,
            app_id TEXT NOT NULL,
            phone_id TEXT NOT NULL,
            access_token TEXT NOT NULL,
            callback_url TEXT NOT NULL,
            verify_token TEXT NOT NULL,
            status TEXT DEFAULT 'inactive',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_id INTEGER,
            sender_number TEXT NOT NULL,
            message_content TEXT NOT NULL,
            message_type TEXT DEFAULT 'text',
            contact_name TEXT DEFAULT '',
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (trigger_id) REFERENCES triggers (id)
        )
    ''')
    
    # Add contact_name column if it doesn't exist (for existing databases)
    try:
        cursor.execute('ALTER TABLE messages ADD COLUMN contact_name TEXT DEFAULT ""')
        print("✅ Added contact_name column to messages table")
    except sqlite3.OperationalError:
        # Column already exists
        pass
    
    conn.commit()
    conn.close()

def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    """Serve the frontend"""
    with open('frontend.html', 'r') as f:
        return f.read()

@app.route('/api/triggers', methods=['GET'])
def get_triggers():
    """Get all triggers"""
    conn = get_db_connection()
    triggers = conn.execute('SELECT * FROM triggers ORDER BY created_at DESC').fetchall()
    conn.close()
    
    return jsonify({
        'success': True,
        'data': [dict(trigger) for trigger in triggers]
    })

@app.route('/api/triggers', methods=['POST'])
def create_trigger():
    """Create a new trigger"""
    data = request.get_json()
    
    # Generate unique node_id
    node_id = str(uuid.uuid4())[:8]
    
    # Generate verify token
    verify_token = hashlib.md5(f"{node_id}{datetime.now()}".encode()).hexdigest()[:16]
    
    # Generate callback URL using environment variable
    base_url = os.getenv('BASE_CALLBACK_URL', request.host_url.rstrip('/'))
    callback_url = f"{base_url}/whatsapp/{node_id}"
    
    
    conn = get_db_connection()
    try:
        cursor = conn.execute('''
            INSERT INTO triggers (node_id, business_name, app_id, phone_id, access_token, callback_url, verify_token)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            node_id,
            data['business_name'],
            data['app_id'],
            data['phone_id'],
            data['access_token'],
            callback_url,
            verify_token
        ))
        trigger_id = cursor.lastrowid
        conn.commit()
        
        # Get the created trigger
        trigger = conn.execute('SELECT * FROM triggers WHERE id = ?', (trigger_id,)).fetchone()
        conn.close()
        
        return jsonify({
            'success': True,
            'data': dict(trigger),
            'message': 'Trigger created successfully!'
        })
    except Exception as e:
        conn.close()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route('/api/triggers/<int:trigger_id>/toggle', methods=['POST'])
def toggle_trigger(trigger_id):
    """Toggle trigger status"""
    conn = get_db_connection()
    trigger = conn.execute('SELECT * FROM triggers WHERE id = ?', (trigger_id,)).fetchone()
    
    if not trigger:
        conn.close()
        return jsonify({'success': False, 'error': 'Trigger not found'}), 404
    
    new_status = 'active' if trigger['status'] == 'inactive' else 'inactive'
    
    conn.execute('UPDATE triggers SET status = ? WHERE id = ?', (new_status, trigger_id))
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'message': f'Trigger {new_status}',
        'status': new_status
    })

@app.route('/api/triggers/<int:trigger_id>', methods=['DELETE'])
def delete_trigger(trigger_id):
    """Delete a trigger and all its messages"""
    conn = get_db_connection()
    trigger = conn.execute('SELECT * FROM triggers WHERE id = ?', (trigger_id,)).fetchone()
    
    if not trigger:
        conn.close()
        return jsonify({'success': False, 'error': 'Trigger not found'}), 404
    
    try:
        # Delete all messages for this trigger first
        conn.execute('DELETE FROM messages WHERE trigger_id = ?', (trigger_id,))
        
        # Delete the trigger
        conn.execute('DELETE FROM triggers WHERE id = ?', (trigger_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Trigger "{trigger["business_name"]}" deleted successfully'
        })
        
    except Exception as e:
        conn.close()
        return jsonify({
            'success': False,
            'error': f'Failed to delete trigger: {str(e)}'
        }), 500

@app.route('/api/dashboard/messages', methods=['GET'])
def get_all_messages():
    """Get all messages from all triggers for dashboard"""
    conn = get_db_connection()
    
    # Get all messages with trigger information
    messages = conn.execute('''
        SELECT 
            m.*,
            t.business_name,
            t.node_id
        FROM messages m
        JOIN triggers t ON m.trigger_id = t.id
        ORDER BY m.received_at DESC
        LIMIT 100
    ''').fetchall()
    conn.close()
    
    # Convert to list of dictionaries and format contact names
    formatted_messages = []
    for message in messages:
        msg_dict = dict(message)
        # Provide both contact name and display name
        if msg_dict.get('contact_name'):
            msg_dict['contact_name_only'] = msg_dict['contact_name']
            msg_dict['display_name'] = f"{msg_dict['contact_name']} ({msg_dict['sender_number']})"
        else:
            msg_dict['contact_name_only'] = None
            msg_dict['display_name'] = msg_dict['sender_number']
        formatted_messages.append(msg_dict)
    
    return jsonify({
        'success': True,
        'data': formatted_messages
    })

@app.route('/api/triggers/<int:trigger_id>/messages', methods=['GET'])
def get_trigger_messages(trigger_id):
    """Get messages for a specific trigger"""
    conn = get_db_connection()
    messages = conn.execute('''
        SELECT * FROM messages 
        WHERE trigger_id = ? 
        ORDER BY received_at DESC
    ''', (trigger_id,)).fetchall()
    conn.close()
    
    # Convert to list of dictionaries and format contact names
    formatted_messages = []
    for message in messages:
        msg_dict = dict(message)
        # Provide both contact name and display name
        if msg_dict.get('contact_name'):
            msg_dict['contact_name_only'] = msg_dict['contact_name']
            msg_dict['display_name'] = f"{msg_dict['contact_name']} ({msg_dict['sender_number']})"
        else:
            msg_dict['contact_name_only'] = None
            msg_dict['display_name'] = msg_dict['sender_number']
        formatted_messages.append(msg_dict)
    
    return jsonify({
        'success': True,
        'data': formatted_messages
    })

@app.route('/api/triggers/<int:trigger_id>/send', methods=['POST'])
def send_message(trigger_id):
    """Send a message via WhatsApp"""
    conn = get_db_connection()
    trigger = conn.execute('SELECT * FROM triggers WHERE id = ?', (trigger_id,)).fetchone()
    
    if not trigger:
        conn.close()
        return jsonify({'success': False, 'error': 'Trigger not found'}), 404
    
    if trigger['status'] != 'active':
        conn.close()
        return jsonify({'success': False, 'error': 'Trigger is not active'}), 400
    
    data = request.get_json()
    to_number = data.get('to_number')
    message_text = data.get('message')
    
    if not to_number or not message_text:
        conn.close()
        return jsonify({'success': False, 'error': 'Missing to_number or message'}), 400
    
    try:
        # Send message via Meta WhatsApp API
        url = f"https://graph.facebook.com/v18.0/{trigger['phone_id']}/messages"
        headers = {
            'Authorization': f"Bearer {trigger['access_token']}",
            'Content-Type': 'application/json'
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {
                "body": message_text
            }
        }
        
        # Log the complete Meta API request
        print("=" * 80)
        print("🚀 META WHATSAPP API REQUEST - COMPLETE LOG")
        print("=" * 80)
        print(f"📅 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🎯 Trigger ID: {trigger_id}")
        print(f"📱 Business Name: {trigger['business_name']}")
        print(f"📞 Phone ID: {trigger['phone_id']}")
        print(f"🔑 Access Token: {trigger['access_token'][:20]}...{trigger['access_token'][-10:]}")
        print()
        print("🌐 API ENDPOINT:")
        print(f"   URL: {url}")
        print(f"   Method: POST")
        print()
        print("📋 REQUEST HEADERS:")
        for key, value in headers.items():
            if key == 'Authorization':
                print(f"   {key}: {value[:20]}...{value[-10:]}")
            else:
                print(f"   {key}: {value}")
        print()
        print("📦 REQUEST PAYLOAD:")
        print(f"   {json.dumps(payload, indent=2)}")
        print()
        print("📤 SENDING REQUEST TO META...")
        
        response = requests.post(url, headers=headers, json=payload)
        
        print("📥 META API RESPONSE:")
        print(f"   Status Code: {response.status_code}")
        print(f"   Response Headers: {dict(response.headers)}")
        print(f"   Response Body: {response.text}")
        print("=" * 80)
        
        if response.status_code == 200:
            result = response.json()
            message_id = result.get('messages', [{}])[0].get('id', 'unknown')
            
            # Save sent message to database
            conn.execute('''
                INSERT INTO messages (trigger_id, sender_number, message_content, message_type)
                VALUES (?, ?, ?, ?)
            ''', (trigger_id, f"sent_to_{to_number}", message_text, 'sent'))
            
            conn.commit()
            conn.close()
            
            return jsonify({
                'success': True,
                'message': 'Message sent successfully',
                'message_id': message_id
            })
        else:
            error_data = response.json() if response.content else {}
            error_msg = error_data.get('error', {}).get('message', 'Failed to send message')
            conn.close()
            return jsonify({
                'success': False,
                'error': f'WhatsApp API Error: {error_msg}'
            }), 400
            
    except Exception as e:
        conn.close()
        print(f"❌ Error sending message: {e}")
        return jsonify({
            'success': False,
            'error': f'Error sending message: {str(e)}'
        }), 500

@app.route('/whatsapp/<node_id>', methods=['GET'])
def verify_webhook(node_id):
    """Verify webhook for Meta"""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    conn = get_db_connection()
    trigger = conn.execute('SELECT * FROM triggers WHERE node_id = ?', (node_id,)).fetchone()
    conn.close()
    
    if not trigger:
        return 'Trigger not found', 404
    
    if mode == 'subscribe' and token == trigger['verify_token']:
        return challenge
    else:
        return 'Verification failed', 403

@app.route('/whatsapp/<node_id>', methods=['POST'])
def receive_webhook(node_id):
    """Receive WhatsApp messages"""
    print(f"🔔 Webhook received for node_id: {node_id}")
    
    conn = get_db_connection()
    trigger = conn.execute('SELECT * FROM triggers WHERE node_id = ?', (node_id,)).fetchone()
    
    if not trigger:
        print(f"❌ Trigger not found for node_id: {node_id}")
        conn.close()
        return 'Trigger not found', 404
    
    print(f"✅ Trigger found: {trigger['business_name']} (ID: {trigger['id']}, Status: {trigger['status']})")
    
    if trigger['status'] != 'active':
        print(f"⚠️ Trigger is inactive, ignoring message")
        conn.close()
        return 'Trigger is inactive', 200
    
    try:
        # Log the complete incoming webhook request from Meta
        print("=" * 80)
        print("📨 META WEBHOOK REQUEST - COMPLETE LOG")
        print("=" * 80)
        print(f"📅 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🎯 Node ID: {node_id}")
        print(f"📱 Business Name: {trigger['business_name']}")
        print()
        print("🌐 INCOMING REQUEST:")
        print(f"   Method: {request.method}")
        print(f"   URL: {request.url}")
        print(f"   Remote Address: {request.remote_addr}")
        print(f"   User Agent: {request.headers.get('User-Agent', 'Unknown')}")
        print()
        print("📋 REQUEST HEADERS:")
        for key, value in request.headers:
            print(f"   {key}: {value}")
        print()
        
        data = request.get_json()
        print("📦 REQUEST BODY (JSON):")
        print(f"   {json.dumps(data, indent=2)}")
        print("=" * 80)
        
        # Handle test calls from Meta (but still process messages if they exist)
        if 'object' in data and data['object'] == 'whatsapp_business_account':
            print("🧪 Meta test call detected, but checking for messages...")
            # Don't return early, continue to process messages if they exist
        
        # Process incoming messages
        if 'entry' in data:
            for entry in data['entry']:
                if 'changes' in entry:
                    for change in entry['changes']:
                        if 'value' in change and 'messages' in change['value']:
                            print(f"💬 Processing {len(change['value']['messages'])} messages")
                            
                            # Extract contact names from the contacts section
                            contact_names = {}
                            if 'contacts' in change['value']:
                                for contact in change['value']['contacts']:
                                    wa_id = contact.get('wa_id')
                                    profile_name = contact.get('profile', {}).get('name', '')
                                    if wa_id and profile_name:
                                        contact_names[wa_id] = profile_name
                                        print(f"👤 Contact name found: {wa_id} -> {profile_name}")
                            
                            for message in change['value']['messages']:
                                sender_number = message['from']
                                message_content = message['text']['body'] if 'text' in message else '[Media Message]'
                                message_type = 'text' if 'text' in message else 'media'
                                
                                # Get contact name if available
                                contact_name = contact_names.get(sender_number, '')
                                display_name = f"{contact_name} ({sender_number})" if contact_name else sender_number
                                
                                print(f"📝 Saving message from {display_name}: {message_content}")
                                
                                # Save message to database with contact name
                                conn.execute('''
                                    INSERT INTO messages (trigger_id, sender_number, message_content, message_type, contact_name)
                                    VALUES (?, ?, ?, ?, ?)
                                ''', (trigger['id'], sender_number, message_content, message_type, contact_name))
        
        conn.commit()
        conn.close()
        print("✅ Webhook processed successfully")
        return 'OK', 200
        
    except Exception as e:
        conn.close()
        print(f"❌ Error processing webhook: {e}")
        import traceback
        traceback.print_exc()
        return 'Error', 500

if __name__ == '__main__':
    init_db()
    print("🚀 Starting Simple WhatsApp Trigger Manager...")
    print(f"🔧 Base Callback URL: {os.getenv('BASE_CALLBACK_URL', 'Not set')}")
    print("📱 Frontend: http://localhost:5000")
    print("🔗 Webhook: http://localhost:5000/whatsapp/<node_id>")
    print()
    print("📋 COMPREHENSIVE LOGGING ENABLED:")
    print("   ✅ Meta API requests (when sending messages)")
    print("   ✅ Meta webhook requests (when receiving messages)")
    print("   ✅ Complete request/response details")
    print("   ✅ Headers, payloads, and responses")
    print("   ✅ Timestamps and trigger information")
    print()
    app.run(host='0.0.0.0', port=5000, debug=True)
