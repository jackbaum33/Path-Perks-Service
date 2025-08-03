import os
import pandas as pd
import uuid
from flask import Flask, jsonify,request,send_from_directory, render_template
from flask_cors import CORS
from dotenv import load_dotenv
import stripe
import os.path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load environment variables
load_dotenv()
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

BITLABS_PUBLIC_TOKEN = os.getenv("BITLABS_PUBLIC_TOKEN")

USER_BY_ID = {}       
DISCOUNT_BY_EMAIL = {}

@app.route('/')
def home():
    return "Service Online"  # Basic status check


@app.route("/api/bitlabs/start", methods=["POST"])
def bitlabs_start():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "email is required"}), 400

    user_id = str(uuid.uuid4())
    USER_BY_ID[user_id] = {"email": email}

    # Return only the public token + a fresh user_id
    return jsonify({
        "publicToken": BITLABS_PUBLIC_TOKEN,
        "userId": user_id
    })

# 2) Webhook: BitLabs -> your backend (configure in BitLabs dashboard)
#    Mark discount eligible when survey is completed.
@app.route("/api/bitlabs/webhook", methods=["POST"])
def bitlabs_webhook():
    # payload format depends on BitLabs; this is a common pattern:
    # Expect JSON like: {"event":"survey_completed","user_id":"...", ...}
    payload = request.get_json(silent=True) or {}
    event = payload.get("event")
    user_id = payload.get("user_id")

    if not user_id:
        return jsonify({"status": "ignored", "reason": "missing user_id"}), 400

    user = USER_BY_ID.get(user_id)
    if not user:
        return jsonify({"status": "ignored", "reason": "unknown user_id"}), 404

    email = user["email"]

    if event == "survey_completed":
        DISCOUNT_BY_EMAIL[email] = {"eligible": True, "percent": 10}
        return jsonify({"status": "ok", "updated": True})

    # Optionally handle other events (e.g., abandoned, disqualified)
    return jsonify({"status": "ok", "updated": False})

# 3) The frontend can check if the email is eligible for a discount
@app.route("/api/discounts/status", methods=["GET"])
def discount_status():
    email = (request.args.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "email is required"}), 400

    rec = DISCOUNT_BY_EMAIL.get(email, {"eligible": False, "percent": 0})
    return jsonify(rec)

def get_google_sheet_data():
    """Fetch enhancement data from local CSV using pandas"""

    base_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base_dir, 'data', 'enhancements.csv')

    try:
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()  # Normalize whitespace

        enhancements = []
        for _, row in df.iterrows():
            try:
                name = row['Enhancement Name']
                description = row['Enhancement Description']
                price = float(row['Enhancement Price'])  # assumed in dollars

                enhancements.append({
                    'name': name,
                    'description': description,
                    'price': int(price * 100)  # convert to cents
                })
            except (KeyError, ValueError) as e:
                print(f"Skipping row due to error: {e}")
                continue

        if not enhancements:
            print("No valid enhancements found in CSV.")
        return enhancements

    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return []

@app.route('/api/enhancements', methods=['GET'])
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
        site_name = str(data.get('siteName'))

        if not isinstance(upsell_items, list):
            return jsonify({'error': 'Invalid items format'}), 400

        line_items = []

        # Optional: add original Squarespace cart as a single line item
        if original_total > 0:
            cleaned_site_name = site_name.removeprefix("www.")
            line_items.append({
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f'Original Cart Total from {cleaned_site_name}',
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
    except ValueError:
        return "Invalid payload", 400
    except stripe.error.SignatureVerificationError:
        return "Invalid signature", 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        customer_email = session.get('customer_details', {}).get('email', 'unknown@example.com')
        customer_name = session.get('customer_details', {}).get('name', 'Valued Customer')  # NEW
        metadata = session.get('metadata', {}) or {}
        website_name = metadata.get('site', 'Your Store')

        line_items = stripe.checkout.Session.list_line_items(session['id'])
        send_confirmation_email(customer_email, customer_name, line_items.data, website_name)
    return '', 200

@app.route('/rack-page')
def rack_page():
    return render_template('order-enhancement-form.html')

def generate_html_email(customer_name, website_name, customer_items, upsell_items):
    subject = f"Your order summary from {website_name}"

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <p>Hi {customer_name},</p>
        <p>Thanks for your order! Below is your complete purchase summary — both from <strong>{website_name}</strong> and the additional services you selected from the <em>Marketplace</em>.</p>

        <h3>✅ Your Items from {website_name}</h3>
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 1em;">
            <tr><th align="left">Item</th><th align="left">Quantity</th><th align="left">Price</th></tr>
            {''.join(f"<tr><td>{item['name']}</td><td>1</td><td>${item['price']:.2f}</td></tr>" for item in customer_items)}
        </table>

        <h3>🔒 Your Add-ons from the Marketplace</h3>
        <table style="width: 100%; border-collapse: collapse;">
            <tr><th align="left">Add-on</th><th align="left">Price</th></tr>
            {''.join(f"<tr><td>{item['name']}</td><td>${item['price']:.2f}</td></tr>" for item in upsell_items)}
        </table>

        <p style="margin-top: 2em;">Need help? Contact us at <a href="mailto:support@path-perks.com">support@path-perks.com</a></p>

        <p>Thanks again for shopping with us — and for enhancing your order with PathPerks!</p>
        <p>🚀<br>The PathPerks Team<br><a href="mailto:support@path-perks.com">support@path-perks.com</a></p>
    </body>
    </html>
    """
    return subject, html


def send_confirmation_email(to_email, customer_name, line_items, website_name):
    sender_email = os.getenv('EMAIL_SENDER')
    sender_password = os.getenv('EMAIL_PASSWORD')

    # Split items into original cart and upsells
    customer_items = []
    upsell_items = []
    for item in line_items:
        if item.description.lower().startswith('original cart total'):
            customer_items.append({'name': 'Original Cart', 'price': item.amount_total / 100})
        else:
            upsell_items.append({'name': item.description, 'price': item.amount_total / 100})

    subject, html_body = generate_html_email(customer_name, website_name, customer_items, upsell_items)

    msg = MIMEMultipart('alternative')
    msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(html_body, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, msg.as_string())
        print("Confirmation email sent to", to_email)
    except Exception as e:
        print("Failed to send email:", e)


@app.route('/images/<filename>')
def serve_image(filename):
    return send_from_directory('data/images', filename)


if __name__ == '__main__':
    app.run(debug=True)
