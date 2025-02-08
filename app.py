import requests
import datetime
from flask import Flask, jsonify, Response
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from bson.json_util import dumps

# Initialize Flask app
app = Flask(__name__)

# MongoDB setup
uri = "mongodb+srv://sargun:ss12ss34ss56ss78ss90@cluster0.fmk5o.mongodb.net/NPKpredictions?retryWrites=true&w=majority"
client = MongoClient(uri, server_api=ServerApi('1'))
db = client['NPKpredictions']
thingspeak_collection = db['thingspeak']

# ThingSpeak API URL
API_URL = 'https://api.thingspeak.com/channels/2197556/feeds.json?api_key=E4TEPORIOIY1VZ3R&results=1175'

# Function to fetch and store the latest valid `field1` data

def fetch_and_store_thingspeak_data():
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        data = response.json()
        feeds = data.get('feeds', [])

        if not feeds:
            print("❌ No ThingSpeak feeds found.")
            return

        valid_entries = []

        print("\n🔍 Checking last 50 entries from ThingSpeak:")
        for feed in feeds:
            field1_str = feed.get('field1', '').strip()

            if field1_str:
                try:
                    field1_values = [float(value) for value in field1_str.split("/")]
                    valid_entries.append({
                        "field1": field1_values,
                        "timestamp": datetime.datetime.utcnow()
                    })
                except ValueError:
                    print(f"⚠ Invalid data skipped: {field1_str}")

        if valid_entries:
            # Avoid inserting duplicates
            for entry in valid_entries:
                existing_entry = thingspeak_collection.find_one({"field1": entry["field1"]})
                if not existing_entry:
                    thingspeak_collection.insert_one(entry)
                    print(f"📌 Stored in MongoDB: {entry}")
                else:
                    print(f"🔄 Duplicate skipped: {entry['field1']}")

        else:
            print("❌ No valid `field1` data found.")

    except requests.exceptions.RequestException as e:
        print(f"🚨 ThingSpeak API request failed: {e}")
    except Exception as e:
        print(f"⚠ Unexpected error: {e}")

# API endpoint to view the latest stored `field1` data
@app.route('/view_thingspeak', methods=['GET'])
def view_thingspeak_data():
    data = thingspeak_collection.find_one(sort=[("timestamp", -1)], projection={'_id': 0, 'field1': 1, 'timestamp': 1})
    return Response(dumps(data), mimetype='application/json') if data else jsonify({'status': 'No data found'})

# Run data fetch function on startup
fetch_and_store_thingspeak_data()

# Start Flask app
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
