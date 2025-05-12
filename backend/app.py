import os
from flask import Flask, jsonify,request
import requests
from flask_cors import CORS
from dotenv import load_dotenv
import pandas as pd
import stripe
import json
import time
import os.path
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

@app.route('/')
def home():
    return "Service Online"  # Basic status check

# Configure Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# Google Sheets configuration
GSHEET_URL = os.getenv('GOOGLE_SHEET_URL')
GSHEET_ID = os.getenv('GOOGLE_SHEET_ID')
GSHEET_API_KEY = os.getenv('GOOGLE_SHEET_API_KEY')  # Optional API key

# Cache configuration
CACHE_FILE = 'cache/product_cache.json'
CACHE_TIMEOUT = int(os.getenv('CACHE_TIMEOUT', 3600))

def get_google_sheet_data():
    """Fetch data from Google Sheet using pandas"""
    try:
        # Option 1: Publicly shared sheet (read-only)
        if GSHEET_URL:
            sheet_url = f"{GSHEET_URL}/export?format=csv"
            df = pd.read_csv(sheet_url)
        
        # Option 2: Using Sheet ID with API key (if needed)
        elif GSHEET_ID and GSHEET_API_KEY:
            sheet_url = f"https://sheets.googleapis.com/v4/spreadsheets/{GSHEET_ID}/values/Sheet1?key={GSHEET_API_KEY}"
            response = requests.get(sheet_url)
            data = response.json()
            df = pd.DataFrame(data['values'][1:], columns=data['values'][0])
        
        else:
            raise ValueError("Missing Google Sheets configuration")
        
        # Process the data
        products = []
        for _, row in df.iterrows():
            try:
                # Use timestamp or name as fallback ID
                product_id = row.get('Timestamp', '') + '-' + row.get('Name', '')

                products.append({
                    'id': str(product_id),
                    'name': row['Item Link'],  # or use row['Name']
                    'price': int(float(row['Revshot Markup']) * 100),  # Convert dollars to cents
                    'image_url': row['Item Image']
                })
            except (KeyError, ValueError) as e:
                print(f"Skipping row due to error: {str(e)}")
                continue
        
        return products
    
    except Exception as e:
        print(f"Error fetching Google Sheet: {str(e)}")
        return []

    
def read_cache():
    """Read cached product data if valid"""
    if not os.path.exists(CACHE_FILE):
        return None
        
    try:
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
            
        cache_time = datetime.fromisoformat(cache_data['timestamp'])
        if datetime.now() - cache_time > timedelta(seconds=CACHE_TIMEOUT):
            return None
            
        return cache_data['products']
    except:
        return None

def write_cache(products):
    """Write product data to cache"""
    cache_data = {
        'timestamp': datetime.now().isoformat(),
        'products': products
    }
    
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache_data, f)

@app.route('/api/products', methods=['GET'])
def get_products():
    """Endpoint to get all products"""
    # Try to read from cache first
    cached_products = read_cache()
    if cached_products is not None:
        return jsonify(cached_products)
    
    # Fetch from Google Sheets if cache is invalid
    try:
        products = get_google_sheet_data()
        write_cache(products)
        return jsonify(products)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/checkout', methods=['POST'])
def create_checkout():
    """Endpoint to handle the checkout process with Stripe Connect"""
    data = request.json
    
    try:
        # Validate input
        if not data or 'items' not in data or 'original_amount' not in data:
            return jsonify({'error': 'Invalid request data'}), 400
            
        items = data['items']
        original_amount = data['original_amount']
        
        # Calculate total amount from our items
        our_amount = sum(item['price'] for item in items)
        total_amount = our_amount + original_amount
        
        # Create line items for Stripe
        line_items = []
        
        # Add original item (from the main website)
        if original_amount > 0:
            line_items.append({
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Original Purchase',
                    },
                    'unit_amount': original_amount,
                },
                'quantity': 1,
            })
        
        # Add our items
        for item in items:
            line_items.append({
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': item['name'],
                    },
                    'unit_amount': item['price'],
                },
                'quantity': 1,
            })
        
        # Create Stripe checkout session with Connect
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=data.get('success_url', 'https://example.com/success'),
            cancel_url=data.get('cancel_url', 'https://example.com/cancel'),
            payment_intent_data={
                'application_fee_amount': our_amount,
                'transfer_data': {
                    'destination': os.getenv('STRIPE_CONNECT_ACCOUNT_ID'),
                },
            },
        )
        
        return jsonify({'session_id': session.id, 'url': session.url})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
