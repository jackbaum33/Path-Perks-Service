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
        if GSHEET_URL:
            sheet_url = f"{GSHEET_URL}/export?format=csv"
            df = pd.read_csv(sheet_url)
        elif GSHEET_ID and GSHEET_API_KEY:
            sheet_url = f"https://sheets.googleapis.com/v4/spreadsheets/{GSHEET_ID}/values/Sheet1?key={GSHEET_API_KEY}"
            response = requests.get(sheet_url)
            data = response.json()
            df = pd.DataFrame(data['values'][1:], columns=data['values'][0])
        else:
            raise ValueError("Missing Google Sheets configuration")

        # Normalize column names
        df.columns = df.columns.str.strip()

        products = []
        for _, row in df.iterrows():
            try:
                product_id = row.get('Timestamp', '') + '-' + row.get('Name', '')

                products.append({
                    'id': str(product_id),
                    'name': row['Name'],
                    'price': int(float(row['Revshot Markup']) * 100),
                    'image_url': row['Item Image']
                })
            except (KeyError, ValueError) as e:
                print(f"Skipping row due to error: {str(e)}")
                print("Available keys:", row.keys())
                continue

        if not products:
            print("No valid products found in sheet.")
        return products

    except Exception as e:
        print(f"Error fetching Google Sheet: {str(e)}")
        return []




@app.route('/api/products', methods=['GET'])
def get_products():
    """Always fetch fresh data from Google Sheets"""
    try:
        products = get_google_sheet_data()
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
