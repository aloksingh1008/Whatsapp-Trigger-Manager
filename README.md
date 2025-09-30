# 📱 Simple WhatsApp Trigger Manager

A super simple WhatsApp Business API trigger manager with just 2 files!

## 🚀 Quick Start

1. **Setup environment:**
   ```bash
   python setup.py
   ```
   This will create a `.env` file with your base callback URL.

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application:**
   ```bash
   python backend.py
   ```

4. **Open your browser:**
   ```
   http://localhost:5000
   ```

## ⚙️ Environment Configuration

The system uses a `.env` file for configuration:

```env
# Base callback URL (without trailing slash)
BASE_CALLBACK_URL=http://localhost:5000

# Flask settings
FLASK_ENV=development
FLASK_DEBUG=True
```

### For Different Environments:

- **Local Development**: `BASE_CALLBACK_URL=http://localhost:5000`
- **Ngrok**: `BASE_CALLBACK_URL=https://your-ngrok-url.ngrok-free.dev`
- **Production**: `BASE_CALLBACK_URL=https://yourdomain.com`

## ✨ Features

- **Simple Setup**: Just 2 files - backend.py and frontend.html
- **Easy Trigger Creation**: Add triggers with business name, app ID, phone ID, and access token
- **Auto-Generated URLs**: System generates callback URLs and verification tokens
- **WhatsApp-like Interface**: View messages in a clean, WhatsApp-style interface
- **Toggle Triggers**: Activate/deactivate triggers easily
- **Real-time Messages**: Receive and view WhatsApp messages instantly

## 📋 How to Use

1. **Create a Trigger:**
   - Click "Add New Trigger"
   - Enter your business name, Meta App ID, Phone Number ID, and Access Token
   - System generates a unique Node ID and callback URL

2. **Configure Meta Webhook:**
   - Use the generated callback URL in your Meta app settings
   - Use the generated verify token for webhook verification

3. **Activate Trigger:**
   - Click the "Activate" button to start receiving messages

4. **View Messages:**
   - Click "Messages" to see all received WhatsApp messages
   - Messages are displayed in a WhatsApp-like interface

## 🔧 Database

The system uses SQLite with two simple tables:
- **triggers**: Stores trigger information
- **messages**: Stores received WhatsApp messages

## 📁 Files

- `backend.py` - Flask backend with all API endpoints
- `frontend.html` - Complete frontend with HTML, CSS, and JavaScript
- `requirements.txt` - Python dependencies
- `triggers.db` - SQLite database (created automatically)

## 🌐 API Endpoints

- `GET /` - Frontend interface
- `GET /api/triggers` - Get all triggers
- `POST /api/triggers` - Create new trigger
- `POST /api/triggers/<id>/toggle` - Toggle trigger status
- `DELETE /api/triggers/<id>` - Delete trigger and all its messages
- `GET /api/triggers/<id>/messages` - Get trigger messages
- `GET /whatsapp/<node_id>` - Webhook verification
- `POST /whatsapp/<node_id>` - Receive WhatsApp messages

That's it! Super simple and easy to use! 🎉
