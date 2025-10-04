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
                completion_message TEXT DEFAULT '',
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
    
    # Create leads table
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_id INTEGER,
                phone_number TEXT NOT NULL,
                contact_name TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                current_question INTEGER DEFAULT 0,
                responses TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (trigger_id) REFERENCES triggers (id)
            )
    ''')
    
    # Create lead_questions table
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS lead_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_id INTEGER,
                question_text TEXT NOT NULL,
                question_type TEXT DEFAULT 'text',
                options TEXT DEFAULT '[]',
                is_required BOOLEAN DEFAULT 1,
                order_index INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
    
    # Add completion_message column if it doesn't exist (for existing databases)
    try:
        cursor.execute('ALTER TABLE triggers ADD COLUMN completion_message TEXT DEFAULT ""')
        print("✅ Added completion_message column to triggers table")
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

# Lead Management API Endpoints

@app.route('/api/triggers/<int:trigger_id>/questions', methods=['GET'])
def get_lead_questions(trigger_id):
    """Get lead questions for a trigger"""
    conn = get_db_connection()
    questions = conn.execute('''
        SELECT * FROM lead_questions 
        WHERE trigger_id = ? 
        ORDER BY order_index ASC
    ''', (trigger_id,)).fetchall()
    conn.close()
    
    return jsonify({
        'success': True,
        'data': [dict(q) for q in questions]
    })

@app.route('/api/triggers/<int:trigger_id>/questions', methods=['POST'])
def create_lead_question(trigger_id):
    """Create a new lead question for a trigger"""
    data = request.get_json()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO lead_questions (trigger_id, question_text, question_type, options, is_required, order_index)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        trigger_id,
        data['question_text'],
        data.get('question_type', 'text'),
        json.dumps(data.get('options', [])),
        data.get('is_required', True),
        data.get('order_index', 0)
    ))
    
    conn.commit()
    question_id = cursor.lastrowid
    conn.close()
    
    return jsonify({
        'success': True,
        'data': {'id': question_id}
    })

@app.route('/api/triggers/<int:trigger_id>/leads', methods=['GET'])
def get_leads(trigger_id):
    """Get all leads for a trigger"""
    conn = get_db_connection()
    leads = conn.execute('''
        SELECT * FROM leads 
        WHERE trigger_id = ? 
        ORDER BY created_at DESC
    ''', (trigger_id,)).fetchall()
    conn.close()
    
    # Parse responses JSON
    formatted_leads = []
    for lead in leads:
        lead_dict = dict(lead)
        try:
            lead_dict['responses'] = json.loads(lead_dict['responses'])
        except:
            lead_dict['responses'] = {}
        formatted_leads.append(lead_dict)
    
    return jsonify({
        'success': True,
        'data': formatted_leads
    })

@app.route('/api/triggers/<int:trigger_id>/leads/<phone_number>', methods=['GET'])
def get_lead_by_phone(trigger_id, phone_number):
    """Get a specific lead by phone number"""
    conn = get_db_connection()
    lead = conn.execute('''
        SELECT * FROM leads 
        WHERE trigger_id = ? AND phone_number = ?
    ''', (trigger_id, phone_number)).fetchone()
    conn.close()
    
    if not lead:
        return jsonify({
            'success': False,
            'message': 'Lead not found'
        })
    
    lead_dict = dict(lead)
    try:
        lead_dict['responses'] = json.loads(lead_dict['responses'])
    except:
        lead_dict['responses'] = {}
    
    return jsonify({
        'success': True,
        'data': lead_dict
    })

@app.route('/api/triggers/<int:trigger_id>/leads/<int:lead_id>', methods=['DELETE'])
def delete_lead(trigger_id, lead_id):
    """Delete a specific lead"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if lead exists and belongs to this trigger
        lead = cursor.execute('''
            SELECT * FROM leads 
            WHERE id = ? AND trigger_id = ?
        ''', (lead_id, trigger_id)).fetchone()
        
        if not lead:
            conn.close()
            return jsonify({
                'success': False,
                'message': 'Lead not found'
            }), 404
        
        # Delete the lead
        cursor.execute('''
            DELETE FROM leads 
            WHERE id = ? AND trigger_id = ?
        ''', (lead_id, trigger_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Lead deleted successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to delete lead: {str(e)}'
        }), 500

@app.route('/api/triggers/<int:trigger_id>/leads', methods=['DELETE'])
def delete_all_leads(trigger_id):
    """Delete all leads for a trigger"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Delete all leads for this trigger
        cursor.execute('''
            DELETE FROM leads 
            WHERE trigger_id = ?
        ''', (trigger_id,))
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Deleted {deleted_count} leads successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to delete leads: {str(e)}'
        }), 500

@app.route('/api/triggers/<int:trigger_id>/completion-message', methods=['PUT'])
def update_completion_message(trigger_id):
    """Update the completion message for a trigger"""
    try:
        data = request.get_json()
        completion_message = data.get('completion_message', '')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update completion message
        cursor.execute('''
            UPDATE triggers 
            SET completion_message = ?
            WHERE id = ?
        ''', (completion_message, trigger_id))
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({
                'success': False,
                'message': 'Trigger not found'
            }), 404
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Completion message updated successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to update completion message: {str(e)}'
        }), 500

@app.route('/api/triggers/<int:trigger_id>/leads', methods=['POST'])
def create_or_update_lead(trigger_id, phone_number, contact_name='', response=''):
    """Create or update a lead with a response"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if lead exists
    existing_lead = cursor.execute('''
        SELECT * FROM leads 
        WHERE trigger_id = ? AND phone_number = ?
    ''', (trigger_id, phone_number)).fetchone()
    
    if existing_lead:
        # Update existing lead
        lead_dict = dict(existing_lead)
        responses = json.loads(lead_dict['responses'])
        
        # Get current question
        questions = cursor.execute('''
            SELECT * FROM lead_questions 
            WHERE trigger_id = ? 
            ORDER BY order_index ASC
        ''', (trigger_id,)).fetchall()
        
        if questions and lead_dict['current_question'] < len(questions):
            current_q = questions[lead_dict['current_question']]
            responses[f"q{current_q['id']}"] = response
            
            # Move to next question
            next_question = lead_dict['current_question'] + 1
            if next_question >= len(questions):
                # All questions answered
                status = 'completed'
            else:
                status = 'active'
            
            cursor.execute('''
                UPDATE leads 
                SET responses = ?, current_question = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (json.dumps(responses), next_question, status, lead_dict['id']))
        else:
            # No questions or all answered
            cursor.execute('''
                UPDATE leads 
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (lead_dict['id'],))
    else:
        # Create new lead
        cursor.execute('''
            INSERT INTO leads (trigger_id, phone_number, contact_name, status, current_question, responses)
            VALUES (?, ?, ?, 'active', 0, '{}')
        ''', (trigger_id, phone_number, contact_name))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'message': 'Lead updated successfully'
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

def handle_lead_generation(trigger_id, phone_number, contact_name, message_content, conn, button_id=None):
    """Handle lead generation logic"""
    try:
        # Check if lead exists
        lead = conn.execute('''
            SELECT * FROM leads 
            WHERE trigger_id = ? AND phone_number = ?
        ''', (trigger_id, phone_number)).fetchone()
        
        # Get questions for this trigger
        questions = conn.execute('''
            SELECT * FROM lead_questions 
            WHERE trigger_id = ? 
            ORDER BY order_index ASC
        ''', (trigger_id,)).fetchall()
        
        if not questions:
            print("📋 No lead questions configured for this trigger")
            return
        
        if not lead:
            # Create new lead
            conn.execute('''
                INSERT INTO leads (trigger_id, phone_number, contact_name, status, current_question, responses)
                VALUES (?, ?, ?, 'active', 0, '{}')
            ''', (trigger_id, phone_number, contact_name))
            
            # Get the new lead
            lead = conn.execute('''
                SELECT * FROM leads 
                WHERE trigger_id = ? AND phone_number = ?
            ''', (trigger_id, phone_number)).fetchone()
            
            print(f"🆕 Created new lead for {phone_number}")
            
            # Send welcome message with interactive buttons
            send_welcome_message(trigger_id, phone_number)
            return
        
        lead_dict = dict(lead)
        current_question_index = lead_dict['current_question']
        
        # Handle button responses
        if button_id:
            if button_id == "start_lead_generation":
                # Start the lead generation process
                if questions:
                    # Update lead to start from question 0
                    conn.execute('''
                        UPDATE leads 
                        SET current_question = 0, status = 'active'
                        WHERE trigger_id = ? AND phone_number = ?
                    ''', (trigger_id, phone_number))
                    
                    first_question = questions[0]
                    send_lead_question(trigger_id, phone_number, first_question)
                else:
                    # Send message that no questions are configured
                    send_simple_message(trigger_id, phone_number, "Sorry, no questions are configured yet. Please contact support.")
                return
            elif button_id == "view_services":
                send_simple_message(trigger_id, phone_number, "Here are our services... (This can be customized per business)")
                return
            elif button_id == "contact_support":
                send_simple_message(trigger_id, phone_number, "Our support team will get back to you shortly. Thank you for contacting us!")
                return
        
        # Check if we have more questions to ask
        if current_question_index < len(questions):
            current_question = questions[current_question_index]
            
            # Save the response
            responses = json.loads(lead_dict['responses'])
            responses[f"q{current_question['id']}"] = message_content
            
            # Move to next question
            next_question_index = current_question_index + 1
            if next_question_index >= len(questions):
                # All questions answered
                status = 'completed'
                print(f"✅ Lead completed for {phone_number}")
                
                # Send completion confirmation message
                send_completion_message(trigger_id, phone_number)
            else:
                status = 'active'
                print(f"📝 Lead progress: {next_question_index}/{len(questions)} questions answered")
            
            # Update lead
            conn.execute('''
                UPDATE leads 
                SET responses = ?, current_question = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (json.dumps(responses), next_question_index, status, lead_dict['id']))
            
            # Send next question if not completed
            if status == 'active' and next_question_index < len(questions):
                next_question = questions[next_question_index]
                send_lead_question(trigger_id, phone_number, next_question)
        else:
            print(f"📋 All questions already answered for {phone_number}")
            
    except Exception as e:
        print(f"❌ Error in lead generation: {str(e)}")

def send_completion_message(trigger_id, phone_number):
    """Send completion confirmation message after all questions are answered"""
    try:
        # Get trigger details
        conn = get_db_connection()
        trigger = conn.execute('''
            SELECT * FROM triggers WHERE id = ?
        ''', (trigger_id,)).fetchone()
        conn.close()
        
        if not trigger:
            print(f"❌ Trigger {trigger_id} not found")
            return
        
        trigger_dict = dict(trigger)
        
        # Create completion message
        if trigger_dict.get('completion_message') and trigger_dict['completion_message'].strip():
            # Use custom completion message
            completion_text = trigger_dict['completion_message']
        else:
            # Use default completion message
            completion_text = f"""🎉 Thank you for providing all the information!

Our team at {trigger_dict['business_name']} has received your details and will contact you within 24 hours to discuss your requirements.

We appreciate your interest and look forward to helping you! 

If you have any urgent questions, feel free to message us anytime.

Best regards,
{trigger_dict['business_name']} Team"""
        
        # Send completion message
        url = f"https://graph.facebook.com/v18.0/{trigger_dict['phone_id']}/messages"
        headers = {
            'Authorization': f'Bearer {trigger_dict["access_token"]}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {
                "body": completion_text
            }
        }
        
        print(f"📤 Sending completion message to {phone_number}")
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            print(f"✅ Completion message sent successfully to {phone_number}")
        else:
            print(f"❌ Failed to send completion message: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error sending completion message: {str(e)}")

def send_simple_message(trigger_id, phone_number, message_text):
    """Send a simple text message"""
    try:
        # Get trigger details
        conn = get_db_connection()
        trigger = conn.execute('''
            SELECT * FROM triggers WHERE id = ?
        ''', (trigger_id,)).fetchone()
        conn.close()
        
        if not trigger:
            print(f"❌ Trigger {trigger_id} not found")
            return
        
        trigger_dict = dict(trigger)
        
        # Send simple text message
        url = f"https://graph.facebook.com/v18.0/{trigger_dict['phone_id']}/messages"
        headers = {
            'Authorization': f'Bearer {trigger_dict["access_token"]}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {
                "body": message_text
            }
        }
        
        print(f"📤 Sending simple message to {phone_number}: {message_text}")
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            print(f"✅ Simple message sent successfully to {phone_number}")
        else:
            print(f"❌ Failed to send simple message: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error sending simple message: {str(e)}")

def send_welcome_message(trigger_id, phone_number):
    """Send welcome message with interactive buttons"""
    try:
        # Get trigger details
        conn = get_db_connection()
        trigger = conn.execute('''
            SELECT * FROM triggers WHERE id = ?
        ''', (trigger_id,)).fetchone()
        conn.close()
        
        if not trigger:
            print(f"❌ Trigger {trigger_id} not found")
            return
        
        trigger_dict = dict(trigger)
        
        # Send interactive welcome message
        url = f"https://graph.facebook.com/v18.0/{trigger_dict['phone_id']}/messages"
        headers = {
            'Authorization': f'Bearer {trigger_dict["access_token"]}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": f"Hi 👋, thanks for reaching out to {trigger_dict['business_name']}! How can we help you today?"
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": "start_lead_generation",
                                "title": "📋 Get Started"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": "view_services",
                                "title": "📌 Our Services"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": "contact_support",
                                "title": "📞 Talk to Us"
                            }
                        }
                    ]
                }
            }
        }
        
        print(f"📤 Sending welcome message to {phone_number}")
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            print(f"✅ Welcome message sent successfully to {phone_number}")
        else:
            print(f"❌ Failed to send welcome message: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error sending welcome message: {str(e)}")

def send_lead_question(trigger_id, phone_number, question):
    """Send a lead question via WhatsApp"""
    try:
        # Get trigger details
        conn = get_db_connection()
        trigger = conn.execute('''
            SELECT * FROM triggers WHERE id = ?
        ''', (trigger_id,)).fetchone()
        conn.close()
        
        if not trigger:
            print(f"❌ Trigger {trigger_id} not found")
            return
        
        trigger_dict = dict(trigger)
        
        # Send message via Meta API
        url = f"https://graph.facebook.com/v18.0/{trigger_dict['phone_id']}/messages"
        headers = {
            'Authorization': f'Bearer {trigger_dict["access_token"]}',
            'Content-Type': 'application/json'
        }
        
        # Prepare message based on question type
        if question['question_type'] == 'multiple_choice':
            options = json.loads(question['options'])
            
            # Create interactive button message
            buttons = []
            for i, option in enumerate(options[:3]):  # WhatsApp allows max 3 buttons
                buttons.append({
                    "type": "reply",
                    "reply": {
                        "id": f"q{question['id']}_option_{i}",
                        "title": option[:20]  # Max 20 characters for button title
                    }
                })
            
            payload = {
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {
                        "text": question['question_text']
                    },
                    "action": {
                        "buttons": buttons
                    }
                }
            }
        else:
            # Send as text message for open-ended questions
            payload = {
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "text",
                "text": {
                    "body": question['question_text']
                }
            }
        
        print(f"📤 Sending lead question to {phone_number}: {question['question_text']}")
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            print(f"✅ Lead question sent successfully to {phone_number}")
        else:
            print(f"❌ Failed to send lead question: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error sending lead question: {str(e)}")

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
            
            # Handle different message types
            if 'text' in message:
                message_content = message['text']['body']
                message_type = 'text'
            elif 'interactive' in message:
                # Handle interactive button responses
                interactive = message['interactive']
                if interactive['type'] == 'button_reply':
                    button_id = interactive['button_reply']['id']
                    button_title = interactive['button_reply']['title']
                    message_content = f"[Button Clicked] {button_title}"
                    message_type = 'interactive'
                    print(f"🔘 Button clicked: {button_title} (ID: {button_id})")
                else:
                    message_content = '[Interactive Message]'
                    message_type = 'interactive'
            else:
                message_content = '[Media Message]'
                message_type = 'media'
            
            # Get contact name if available
            contact_name = contact_names.get(sender_number, '')
            display_name = f"{contact_name} ({sender_number})" if contact_name else sender_number
            
            print(f"📝 Saving message from {display_name}: {message_content}")
            
            # Save message to database with contact name
            conn.execute('''
                INSERT INTO messages (trigger_id, sender_number, message_content, message_type, contact_name)
                VALUES (?, ?, ?, ?, ?)
            ''', (trigger['id'], sender_number, message_content, message_type, contact_name))
            
            # Handle lead generation with button response processing
            if 'interactive' in message and interactive['type'] == 'button_reply':
                button_id = interactive['button_reply']['id']
                button_title = interactive['button_reply']['title']
                handle_lead_generation(trigger['id'], sender_number, contact_name, button_title, conn, button_id)
            else:
                handle_lead_generation(trigger['id'], sender_number, contact_name, message_content, conn)
        
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
