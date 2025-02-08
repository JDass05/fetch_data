import pickle
from flask import Flask, jsonify, request
import pandas as pd
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import requests
import datetime
import ee  # Google Earth Engine library
from bson import json_util  # Import json_util for BSON handling
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import os

# Load your trained model
file_path = 'Final_model_iguess.pkl'
with open(file_path, 'rb') as model_file:
    model = pickle.load(model_file)
    
# Initialize Flask app
app = Flask(__name__)

# MongoDB setup
uri = "mongodb+srv://sargun:ss12ss34ss56ss78ss90@cluster0.fmk5o.mongodb.net/hackTU?retryWrites=true&w=majority"
if not uri:
    raise ValueError("MongoDB URI is not set.")

# Google Earth Engine (GEE) setup
service_account = 'sargun@sargun20.iam.gserviceaccount.com'
key_file = 'sargun20-e5f0e5945226.json'
credentials = ee.ServiceAccountCredentials(service_account, key_file)
ee.Initialize(credentials)
sentinel2_collection = 'COPERNICUS/S2'

# NASA LaRC API setup
NASA_API_URL = "https://power.larc.nasa.gov/api/temporal/daily/point?start=20240729&end=20240729&latitude=31.0741&longitude=76.0232&community=re&parameters=T2M%2CRH2M%2CPS&format=json&header=true&time-standard=lst"

# ThingSpeak API setup
API_KEY = "E4TEPORIOIY1VZ3R"
API_URL = 'https://api.thingspeak.com/channels/2197556/feeds.json?api_key=E4TEPORIOIY1VZ3R&results=2000'

# MongoDB client and database setup
try:
    client = MongoClient(uri, server_api=ServerApi('1'))
    client.admin.command('ping')
    print("Successfully connected to MongoDB!")
    db = client['hackTU']
    thingspeak_collection = db['thingspeak']
    nasa_collection = db['nasa_larc']
    gee_collection = db['google_earth_engine']
except Exception as e:
    print(f"MongoDB connection failed: {e}")
    exit()

# Function to fetch and store ThingSpeak data
# Define parameter names in order
PARAMETER_NAMES = [
    "Soil Moisture", "Soil pH", "Soil Temperature", 
    "Air Temperature", "Humidity", "Nutrient Level", "Light Intensity"
]

def fetch_thingspeak_data():
    """Fetches the latest valid ThingSpeak data and stores it in MongoDB."""
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        data = response.json().get('feeds', [])

        if not data:
            print("No ThingSpeak data found.")
            return None

        for feed in reversed(data):  # Start from the latest entry
            field1_str = feed.get('field1', '').strip()

            if field1_str:
                try:
                    field1_values = [float(value) for value in field1_str.split("/")]
                    latest_thingspeak_data = {PARAMETER_NAMES[i]: field1_values[i] for i in range(len(field1_values))}
                    latest_thingspeak_data["timestamp"] = datetime.datetime.utcnow()

                    print("\n📌 Latest ThingSpeak Data Found:")
                    for key, value in latest_thingspeak_data.items():
                        print(f"{key}: {value}")

                    # Store in MongoDB
                    thingspeak_collection.insert_one(latest_thingspeak_data)
                    print("✅ ThingSpeak data stored in MongoDB.")

                    return latest_thingspeak_data  # Stop checking after first valid data

                except ValueError:
                    pass  # Ignore invalid values

        print("No valid `field1` data found.")
        return None

    except requests.exceptions.RequestException as e:
        print(f"ThingSpeak API request failed: {e}")
        return None
# Function to fetch and store NASA LaRC data
def fetch_and_store_nasa_data():
    try:
        response = requests.get(NASA_API_URL)
        response.raise_for_status()
        data = response.json()
        parameters = data.get('properties', {}).get('parameter', {})
        new_data = {
            "T2M": parameters.get('T2M', {}).get('20240729', 'N/A'),
            "RH2M": parameters.get('RH2M', {}).get('20240729', 'N/A'),
            "PS": parameters.get('PS', {}).get('20240729', 'N/A'),
            "timestamp": datetime.datetime.utcnow()
        }

        # Check if the latest data is new or if it needs to be updated
        latest_db_data = nasa_collection.find_one(sort=[("timestamp", -1)])
        if not latest_db_data or latest_db_data['timestamp'] != new_data['timestamp']:
            nasa_collection.insert_one(new_data)
            print(f"NASA LaRC data stored in MongoDB: {new_data}")
        else:
            print("No new NASA data to store.")
    except requests.exceptions.RequestException as e:
        print(f"NASA API request failed: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

# Function to fetch and store Google Earth Engine data

def fetch_and_store_gee_data(lat=30.91028, lon=75.81886, radius=10, days_back=30):
    try:
        point = ee.Geometry.Point([lon, lat])
        buffer = point.buffer(radius * 1000)

        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=days_back)

        s2 = ee.ImageCollection(sentinel2_collection) \
            .filterBounds(buffer) \
            .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')) \
            .sort('system:time_start', False)

        if s2.size().getInfo() == 0:
            print("No images found for the specified location and date range.")
            return None

        recent_image = s2.first().divide(10000.0)  

        def add_indices(image):
            NIR = image.select('B8')
            RED = image.select('B4')
            GREEN = image.select('B3')
            BLUE = image.select('B2')
            RED_EDGE = image.select('B5')
            SWIR1 = image.select('B11')
            SWIR2 = image.select('B12')

            indices = {
                'ARI': image.expression('(1 / GREEN) - (1 / RED_EDGE)', {'GREEN': GREEN, 'RED_EDGE': RED_EDGE}).rename('ARI'),
                'CAI': image.expression('0.5 * ((SWIR1 + SWIR2) - NIR)', {'SWIR1': SWIR1, 'SWIR2': SWIR2, 'NIR': NIR}).rename('CAI'),
                'CIRE': NIR.divide(RED_EDGE).subtract(1).rename('CIRE'),
                'DWSI': NIR.divide(SWIR1).rename('DWSI'),
                'EVI': image.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1.0001))', {'NIR': NIR, 'RED': RED, 'BLUE': BLUE}).rename('EVI'),
                'GCVI': NIR.divide(GREEN).subtract(1).rename('GCVI'),
                'MCARI': image.expression('((RED_EDGE - RED) - 0.2 * (RED_EDGE - GREEN)) * (RED_EDGE / RED)', {'RED_EDGE': RED_EDGE, 'RED': RED, 'GREEN': GREEN}).rename('MCARI'),
                'NDVI': NIR.subtract(RED).divide(NIR.add(RED)).rename('NDVI'),
                'SIPI': image.expression('(NIR - BLUE) / (NIR - RED)', {'NIR': NIR, 'BLUE': BLUE, 'RED': RED}).rename('SIPI')
            }
            return image.addBands(list(indices.values()))

        recent_image_with_indices = add_indices(recent_image)
        sample = recent_image_with_indices.sample(region=point, scale=10, numPixels=1).first()
        indices_dict = sample.toDictionary().getInfo()

        required_indices = {key: indices_dict.get(key, "N/A") for key in ['ARI', 'CAI', 'CIRE', 'DWSI', 'EVI', 'GCVI', 'MCARI', 'NDVI', 'SIPI']}
        required_indices['timestamp'] = datetime.datetime.utcnow()

        gee_collection.insert_one(required_indices)
        print("GEE Data Stored:", required_indices)
    except Exception as e:
        print(f" GEE Fetch Error: {e}")

    except Exception as e:
        print(f"GEE Error: {e}")
@app.route('/get_all_data', methods=['GET'])
def get_all_data():
    thingspeak_data = thingspeak_collection.find_one(sort=[("timestamp", -1)])
    nasa_data = nasa_collection.find_one(sort=[("timestamp", -1)])
    gee_data = gee_collection.find_one(sort=[("timestamp", -1)])

    response_data = {
        "ThingSpeak Data": thingspeak_data or "No Data Available",
        "NASA LaRC Data": nasa_data or "No Data Available",
        "GEE Data": gee_data or "No Data Available"
    }

    return json_util.dumps(response_data), 200

# Wrapper function for scheduled GEE data fetch
def scheduled_fetch_gee_data():
    fetch_and_store_gee_data(30.91028, 75.81886, 10)

# Initialize scheduler
scheduler = BackgroundScheduler()

# Schedule tasks
scheduler.add_job(fetch_thingspeak_data, 'interval', minutes=2)
scheduler.add_job(fetch_and_store_nasa_data, 'interval', days=1)
scheduler.add_job(scheduled_fetch_gee_data, 'interval', days=1)

# Start the scheduler
scheduler.start()

from flask import Response
from bson.json_util import dumps

@app.route('/predict', methods=['GET'])
def make_prediction():
    try:
        # Retrieve the latest data from MongoDB collections
        thingspeak_data = thingspeak_collection.find_one(sort=[("timestamp", -1)])
        nasa_data = nasa_collection.find_one(sort=[("timestamp", -1)])
        gee_data = gee_collection.find_one(sort=[("timestamp", -1)])
        
        if not thingspeak_data or not nasa_data or not gee_data:
            return jsonify({'status': 'Data not available for prediction'}), 404

        # Define feature names for clarity
        feature_names = [
            'n1', 'p1', 'k1',  # ThingSpeak data
            'T2M', 'RH2M', 'PS',  # NASA LaRC data
            'NDVI', 'EVI', 'ARI', 'CAI', 'CIRE', 'DWSI', 'GCVI', 'MCARI'  # GEE data
        ]

        # Extract features from MongoDB documents and fill missing ones as needed
        features = [
            thingspeak_data.get('n1', 0),
            thingspeak_data.get('p1', 0),
            thingspeak_data.get('k1', 0),
            nasa_data.get('T2M', 0),
            nasa_data.get('RH2M', 0),
            nasa_data.get('PS', 0),
            gee_data.get('NDVI', 0),
            gee_data.get('EVI', 0),
            gee_data.get('ARI', 0),
            gee_data.get('CAI', 0),
            gee_data.get('CIRE', 0),
            gee_data.get('DWSI', 0),
            gee_data.get('GCVI', 0),
            gee_data.get('MCARI', 0)
        ]

        # Combine feature names and values into a dictionary
        feature_data = dict(zip(feature_names, features))

        # Convert to DataFrame as expected by the model
        predict_data = pd.DataFrame([features])

        # Make a prediction
        prediction = model.predict(predict_data)

        # Unpack the first (and only) prediction row and map it to N, P, K labels
        npk_prediction = {
            "N": float(prediction[0][0]),  # Convert to float for JSON serialization
            "P": float(prediction[0][1]),
            "K": float(prediction[0][2])
        }

        # Return prediction and feature data as JSON response
        return jsonify({
            "Prediction (NPK)": npk_prediction,
            "Input_Features": feature_data
        })
    except Exception as e:
        return jsonify({"Error": str(e)}), 500


# Main execution block
if __name__ == '__main__':
    # Automatically fetch and store data on startup
    fetch_thingspeak_data()
    fetch_and_store_nasa_data()
    fetch_and_store_gee_data()

    # Start the Flask application
    app.run(debug=True, host='0.0.0.0', port=5000)