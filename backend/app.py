import os
from flask import Flask, jsonify,request
from flask_cors import CORS
from dotenv import load_dotenv
import stripe
import os.path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

@app.route('/')
def home():
    return "Service Online"  # Basic status check

# Google Sheets configuration
GSHEET_URL = os.getenv('GOOGLE_SHEET_URL')
GSHEET_ID = os.getenv('GOOGLE_SHEET_ID')
GSHEET_API_KEY = os.getenv('GOOGLE_SHEET_API_KEY')  # Optional API key

# Cache configuration
CACHE_FILE = 'cache/product_cache.json'
CACHE_TIMEOUT = int(os.getenv('CACHE_TIMEOUT', 3600))

def get_google_sheet_data():
    """Fetch data from local CSV using pandas"""
    import os
    import pandas as pd

    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, 'data', 'data.csv')

    try:
        df = pd.read_csv(csv_path)

        # Normalize column names
        df.columns = df.columns.str.strip()

        products = []
        for _, row in df.iterrows():
            try:
                product_id = row.get('Timestamp', '') + '-' + row.get('Name', '')

                products.append({
                    'id': str(product_id),
                    'name': row['Item Title'],
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

@app.route('/api/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        data = request.get_json()
        upsell_items = data.get('items', [])
        original_total = data.get('originalTotal', 0)

        if not isinstance(upsell_items, list):
            return jsonify({'error': 'Invalid items format'}), 400

        line_items = []

        # Optional: add original Squarespace cart as a single line item
        if original_total > 0:
            line_items.append({
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Original Cart Total',
                    },
                    'unit_amount': original_total,
                },
                'quantity': 1,
            })

        # Add upsell selections
        for item in upsell_items:
            name = item.get('name')
            price = item.get('price')
            if name and isinstance(price, int):
                line_items.append({
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {'name': name},
                        'unit_amount': price,
                    },
                    'quantity': 1
                })

        if not line_items:
            return jsonify({'error': 'No valid items for checkout'}), 400

        # Create Stripe checkout session
        origin = request.headers.get('Origin', 'https://example.com')  # Fallback to default

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            mode='payment',
            line_items=line_items,
            success_url=f'{origin}/thank-you',
            cancel_url=f'{origin}/checkout-canceled'
        )
        
        return jsonify({'url': session.url})

    except Exception as e:
        print("Stripe error:", e)
        return jsonify({'error': str(e)}), 500
    

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('stripe-signature')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError as e:
        return "Invalid payload", 400
    except stripe.error.SignatureVerificationError:
        return "Invalid signature", 400

    # Only handle completed checkout
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        customer_email = session.get('customer_details', {}).get('email', 'unknown@example.com')
        line_items = stripe.checkout.Session.list_line_items(session['id'])

        send_confirmation_email(customer_email, line_items.data)

    return '', 200

def send_confirmation_email(to_email, line_items):
    sender_email = os.getenv('EMAIL_SENDER')
    sender_password = os.getenv('EMAIL_PASSWORD')

    subject = "Thank you for your order!"
    body = "Your purchase includes:\n\n"
    for item in line_items:
        body += f"- {item.description}: ${item.amount_total / 100:.2f}\n"

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, msg.as_string())
        print("Confirmation email sent to", to_email)
    except Exception as e:
        print("Failed to send email:", e)

@app.route('/api/cart', methods=['POST', 'GET'])
def cart_total():

    if request.method == 'POST':
        data = request.get_json()
        amount = data.get('amount')
        if amount is None:
            return jsonify({'error': 'Missing amount'}), 400

        latest_cart_total = amount
        return jsonify({'message': 'Cart total stored'}), 200

    elif request.method == 'GET':
        if latest_cart_total is None:
            return jsonify({'error': 'No cart total stored yet'}), 404
        return jsonify({'amount': latest_cart_total}), 200

if __name__ == '__main__':
    app.run(debug=True)
