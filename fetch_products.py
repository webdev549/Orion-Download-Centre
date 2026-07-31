import requests
import json
import time
import os
import re
from datetime import datetime
import pytz
import sys
import base64

# -------------------------
# Get credentials from environment variables
# -------------------------
SHOPIFY_STORE = os.environ.get('SHOPIFY_STORE', 'abc-xx.myshopify.com')
CLIENT_ID = os.environ.get('SHOPIFY_CLIENT_ID', 'your_client_id_here')
CLIENT_SECRET = os.environ.get('SHOPIFY_SECRET', 'your_client_secret_here')

API_VERSION = os.environ.get('API_VERSION', '2024-10')

print("=" * 60)
print("🔍 CONFIGURATION:")
print(f"SHOPIFY_STORE: {SHOPIFY_STORE}")
print(f"API_VERSION: {API_VERSION}")
print(f"CLIENT_ID: {CLIENT_ID[:15] if CLIENT_ID else 'NOT SET'}...")
print("=" * 60)

ACCESS_TOKEN = None
HEADERS = {}
REQUEST_DELAY = 0.5

def log_message(message):
    """Simple logging with AEST time"""
    try:
        aest = pytz.timezone('Australia/Sydney')
        timestamp = datetime.now(aest).strftime('%Y-%m-%d %H:%M:%S %Z')
        print(f"{timestamp} - {message}")
    except:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"{timestamp} - {message}")

# -------------------------
# Authentication
# -------------------------
def get_access_token():
    """Get access token using client credentials"""
    global ACCESS_TOKEN, HEADERS
    
    url = f"https://{SHOPIFY_STORE}/admin/oauth/access_token"
    
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    
    try:
        log_message(" Getting access token...")
        response = requests.post(url, data=payload, timeout=30)
        
        if response.status_code == 200:
            token_data = response.json()
            ACCESS_TOKEN = token_data.get('access_token')
            HEADERS = {
                "X-Shopify-Access-Token": ACCESS_TOKEN,
                "Content-Type": "application/json"
            }
            log_message(" Access token obtained")
            
            # Check token scopes
            check_token_scopes()
            
            return True
        else:
            log_message(f" Failed to get access token: {response.status_code}")
            log_message(f"Response: {response.text}")
            return False
    except Exception as e:
        log_message(f" Error getting access token: {str(e)}")
        return False

def check_token_scopes():
    """Check what scopes the current token has"""
    try:
        url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/shop.json"
        response = requests.get(url, headers=HEADERS, timeout=30)
        if response.status_code == 200:
            # Check response headers for scope info
            scopes = response.headers.get('X-Shopify-Access-Token-Scopes', 'Not provided')
            log_message(f" Token scopes: {scopes}")
            
            if 'write_theme_files' not in scopes:
                log_message(" WARNING: Token may not have write_theme_files scope!")
        else:
            log_message(f" Could not check scopes: {response.status_code}")
    except Exception as e:
        log_message(f" Error checking scopes: {str(e)}")

def verify_connection():
    """Test if we can connect to Shopify API"""
    test_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/shop.json"
    
    try:
        log_message(f"🔍 Testing connection...")
        response = requests.get(test_url, headers=HEADERS, timeout=30)
        if response.status_code == 200:
            shop_data = response.json()
            shop_name = shop_data.get('shop', {}).get('name', 'Unknown')
            log_message(f" Connected to: {shop_name}")
            return True
        else:
            log_message(f" Connection failed: {response.status_code}")
            return False
    except Exception as e:
        log_message(f" Connection error: {str(e)}")
        return False

# -------------------------
# Fetch all products
# -------------------------
def get_all_products():
    products = []
    url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/products.json?limit=250"
    
    while url:
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            
            if response.status_code != 200:
                log_message(f" Error fetching products: {response.status_code}")
                break
            
            data = response.json()
            products_batch = data.get("products", [])
            products += products_batch
            log_message(f" Fetched {len(products_batch)} products (Total: {len(products)})")
            
            # Check for next page
            link_header = response.headers.get('Link', '')
            next_url = None
            
            if link_header:
                links = link_header.split(',')
                for link in links:
                    if 'rel="next"' in link:
                        next_url = link.split('<')[1].split('>')[0]
                        break
            
            url = next_url
            
        except Exception as e:
            log_message(f" Error fetching products: {str(e)}")
            break
    
    return products

# -------------------------
# Fetch product documents (both instruction manual and datasheet)
# -------------------------
def get_product_documents(product_id):
    """Fetch all required metafields for a product"""
    time.sleep(REQUEST_DELAY)
    try:
        url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
        
        response = requests.get(url, headers=HEADERS, timeout=30)
        
        instructions = ""
        datasheet = ""
        sdoc = ""
        extension_rod_matrix = ""
        
        if response.status_code == 200:
            metafields = response.json().get("metafields", [])
            
            for metafield in metafields:
                if metafield.get("namespace") == "custom":
                    key = metafield.get("key")
                    value = sanitize_string(metafield.get("value", ""))
                    
                    if key == "instruction_manual_url":
                        instructions = value
                        if value:
                            log_message(f" Found instructions for product {product_id}")
                    
        
        return instructions, datasheet, sdoc, extension_rod_matrix
            
    except Exception as e:
        log_message(f" Error fetching product documents: {str(e)}")
        return "", "", "", ""

# -------------------------
# Sanitize string for JSON
# -------------------------
def sanitize_string(s):
    if not s:
        return ""
    s = str(s)
    s = re.sub(r'[^\x00-\x7F]+', '', s)
    s = s.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
    s = s.replace('"', '\\"').replace("'", "\\'")
    return s

# -------------------------
# Generate JS file
# -------------------------
def generate_js_file(products, filename="product-documents.js"):
    output = []
    total_products = len(products)
    
    log_message(f" Processing {total_products} products...")
    
    for index, product in enumerate(products):
        if index % 10 == 0 and index > 0:
            log_message(f" Processed {index}/{total_products} products")
        
        # Fetch both documents in one call
        instructions  = get_product_documents(product["id"])
        
        thumbnail = ""
        if product.get("images"):
            thumbnail = sanitize_string(product["images"][0]["src"])
        
        for variant in product.get("variants", []):
            if variant.get("sku"):
                output.append({
                    "sku": sanitize_string(variant.get("sku")),
                    "title": sanitize_string(product.get("title")),
                    "instructions": instructions,
                    "thumbnail": thumbnail
                })
    
    # Generate JS content
    js_content = "window.products = [\n"
    
    for i, product in enumerate(output):
        js_content += "  {\n"
        js_content += f'    "sku": "{product["sku"]}",\n'
        js_content += f'    "title": "{product["title"]}",\n'
        js_content += f'    "instructions": "{product["instructions"]}",\n'
        js_content += f'    "thumbnail": "{product["thumbnail"]}"\n'
        js_content += "  }"
        if i < len(output) - 1:
            js_content += ","
        js_content += "\n"
    
    js_content += "];"
    
    file_path = os.path.abspath(filename)
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(js_content)
        
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            log_message(f" Generated {filename}")
            log_message(f"   Path: {file_path}")
            log_message(f"   Size: {file_size} bytes")
            log_message(f"   Variants: {len(output)}")
            return file_path, len(output)
        else:
            log_message(f" File was not created")
            return None, 0
            
    except Exception as e:
        log_message(f" Error writing file: {str(e)}")
        return None, 0

# -------------------------
# List available themes
# -------------------------
def list_themes():
    """List all available themes"""
    try:
        themes_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/themes.json"
        response = requests.get(themes_url, headers=HEADERS, timeout=30)
        
        if response.status_code == 200:
            themes = response.json().get('themes', [])
            log_message(f"\n Available themes ({len(themes)} found):")
            for theme in themes:
                log_message(f"   • {theme['name']}")
                log_message(f"     ID: {theme['id']}")
                log_message(f"     Role: {theme.get('role', 'N/A')}")
            return themes
        else:
            log_message(f" Cannot list themes: {response.status_code}")
            log_message(f"Response: {response.text}")
            return []
    except Exception as e:
        log_message(f" Error listing themes: {str(e)}")
        return []

# -------------------------
# Upload file to Shopify theme
# -------------------------
def upload_to_shopify(file_path):
    """Upload the generated JS file to the active Shopify theme"""

    try:
        if not os.path.exists(file_path):
            log_message(f" File not found: {file_path}")
            return False

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        filename = os.path.basename(file_path)
        asset_key = f"assets/{filename}"

        # Get active/main theme
        themes = list_themes()
        active_theme = next((t for t in themes if t.get("role") == "main"), None)

        if not active_theme:
            log_message(" No active theme found")
            return False

        theme_id = active_theme["id"]

        upload_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/themes/{theme_id}/assets.json"

        payload = {
            "asset": {
                "key": asset_key,
                "value": content
            }
        }

        response = requests.put(upload_url, headers=HEADERS, json=payload, timeout=30)

        if response.status_code in [200, 201]:
            log_message("Successfully uploaded!")
            return True

        log_message(f" Upload failed: {response.status_code}")
        log_message(response.text)
        return False

    except Exception as e:
        log_message(f" Upload error: {str(e)}")
        return False

def try_alternative_upload(content, filename, theme_id):
    """Try alternative upload methods"""
    
    # Method 2: Try without 'assets/' prefix
    try:
        asset_key = filename
        upload_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/themes/{theme_id}/assets.json"
        
        payload = {
            "asset": {
                "key": asset_key,
                "value": content
            }
        }
        
        log_message(f"\n Trying alternative key format: {asset_key}")
        response = requests.put(upload_url, headers=HEADERS, json=payload, timeout=30)
        
        if response.status_code in [200, 201]:
            log_message(f" Successfully uploaded with alternative key!")
            return True
    except Exception as e:
        log_message(f" Alternative method 1 failed: {str(e)}")
    
    # Method 3: Try with base64 attachment
    try:
        attachment = base64.b64encode(content.encode()).decode()
        asset_key = f"assets/{filename}"
        upload_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/themes/{theme_id}/assets.json"
        
        payload = {
            "asset": {
                "key": asset_key,
                "attachment": attachment
            }
        }
        
        log_message(f"\n🔄 Trying attachment method...")
        response = requests.put(upload_url, headers=HEADERS, json=payload, timeout=30)
        
        if response.status_code in [200, 201]:
            log_message(f" Successfully uploaded with attachment!")
            return True
    except Exception as e:
        log_message(f" Attachment method failed: {str(e)}")
    
    return False

# -------------------------
# Main function
# -------------------------
def main():
    try:
        aest = pytz.timezone('Australia/Sydney')
        start_time = datetime.now(aest)
    except:
        start_time = datetime.now()
    
    log_message("=" * 60)
    log_message(f" STARTING SHOPIFY PRODUCT SYNC")
    log_message(f" Started at: {start_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    log_message("=" * 60)
    
    # Get access token
    if not get_access_token():
        log_message(" Failed to authenticate")
        return 1
    
    # Verify connection
    if not verify_connection():
        log_message(" Cannot connect to Shopify")
        return 1
    
    # Fetch products
    log_message("\n Fetching products...")
    products = get_all_products()
    
    if not products:
        log_message(" No products found")
        return 1
    
    log_message(f" Found {len(products)} products")
    
    # Generate JS file
    log_message("\n Generating file...")
    file_path, variant_count = generate_js_file(products)
    
    if not file_path:
        log_message(" Failed to generate file")
        return 1
    
    # Upload to Shopify
    log_message("\n🔼 Uploading to Shopify...")
    if upload_to_shopify(file_path):
        end_time = datetime.now(aest) if 'aest' in locals() else datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        log_message("\n" + "=" * 60)
        log_message(" SYNC COMPLETED SUCCESSFULLY!")
        log_message(f" Duration: {duration:.2f} seconds")
        log_message(f" Products: {len(products)}")
        log_message(f" Variants: {variant_count}")
        log_message(f" Uploaded: assets/{os.path.basename(file_path)}")
        log_message("=" * 60)
        return 0
    else:
        log_message("\n Upload failed")
        log_message(f" File saved locally at: {file_path}")
        log_message("\nPossible issues:")
        log_message("1. The app may not have 'write_theme_files' scope")
        log_message("2. The theme ID might be incorrect")
        log_message("3. The access token might be expired")
        return 1

if __name__ == "__main__":
    import signal
    
    def timeout_handler(signum, frame):
        log_message(" SCRIPT TIMEOUT")
        exit(1)
    
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(2700)
    
    try:
        exit_code = main()
        signal.alarm(0)
        exit(exit_code)
    except Exception as e:
        log_message(f" CRITICAL ERROR: {str(e)}")
        exit(1)
