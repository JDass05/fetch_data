from flask import Flask, jsonify, request
import numpy as np
import pandas as pd
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import requests
import datetime
import ee  # Google Earth Engine library
from bson import json_util  # Import json_util for BSON handling
from apscheduler.schedulers.background import BackgroundScheduler
import pickle

# Load your trained model
file_path = 'Final_model_iguess.pkl'
with open(file_path, 'rb') as model_file:
    model = pickle.load(model_file)

# Initialize Flask app
app = Flask(__name__)

# MongoDB setup
uri = "mongodb+srv://sargun:ss12ss34ss56ss78ss90@cluster0.fmk5o.mongodb.net/NPKpredictions?retryWrites=true&w=majority"
if not uri:
    raise ValueError("MongoDB URI is not set.")

# Google Earth Engine (GEE) setup
service_account = 'sargun@sargun20.iam.gserviceaccount.com'
key_file = 'sargun20-af558cd29ee0.json'
credentials = ee.ServiceAccountCredentials(service_account, key_file)
ee.Initialize(credentials)
sentinel2_collection = 'COPERNICUS/S2'

# NASA LaRC API setup
NASA_API_URL = "https://power.larc.nasa.gov/api/temporal/daily/point?start=20240729&end=20240729&latitude=31.0741&longitude=76.0232&community=re&parameters=T2M%2CRH2M%2CPS&format=json&header=true&time-standard=lst"

# ThingSpeak API setup
API_KEY = "LELEVX9B3SDHSFZ9"
API_URL = f'https://api.thingspeak.com/channels/2187169/feeds.json?api_key={API_KEY}&results=1'

# MongoDB client and database setup
try:
    client = MongoClient(uri, server_api=ServerApi('1'))
    client.admin.command('ping')
    print("Successfully connected to MongoDB!")
    db = client['NPKpredictions']
    thingspeak_collection = db['thingspeak']
    nasa_collection = db['nasa_larc']
    gee_collection = db['google_earth_engine']
except Exception as e:
    print(f"MongoDB connection failed: {e}")
    exit()

# Function to fetch and store ThingSpeak data
def fetch_and_store_thingspeak_data():
    try:
        data_dict = {
            "c1": 75.7,
            "hp1": 1.07,
            "k1": 54,
            "m1": 9,
            "n1": 539,
            "p1": 38,
            "t1": 245,
            "timestamp": datetime.datetime.utcnow()
        }
        # Insert data into MongoDB
        result = thingspeak_collection.insert_one(data_dict)
        print("Data inserted successfully:", result.inserted_id)
    except Exception as e:
        print(f"Failed to insert data into MongoDB: {e}")



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
def fetch_and_store_gee_data():
    try:
        lat, lon, radius = 30.21813, 76.40966, 10
        days_back = 30
        point = ee.Geometry.Point([lon, lat])
        buffer = point.buffer(radius * 1000)

        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=days_back)
        s2 = (ee.ImageCollection(sentinel2_collection)
              .filterBounds(buffer)
              .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
              .sort('system:time_start', False))
        recent_image = s2.first()

        # Define vegetation indices calculations
        def add_indices(image):
            indices = {
                'NDVI': image.normalizedDifference(['B8', 'B4']).rename('NDVI'),
                'EVI': image.expression(
                    '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
                    {'NIR': image.select('B8'), 'RED': image.select('B4'), 'BLUE': image.select('B2')}
                ).rename('EVI'),
                'ARI': image.expression(
                    '(1 / GREEN) - (1 / REDEDGE1)',
                    {'GREEN': image.select('B3'), 'REDEDGE1': image.select('B5')}
                ).rename('ARI'),
                'CAI': image.expression(
                    'SWIR1 / SWIR2',
                    {'SWIR1': image.select('B11'), 'SWIR2': image.select('B12')}
                ).rename('CAI'),
                'CIRE': image.expression(
                    '(NIR / REDEDGE1) - 1',
                    {'NIR': image.select('B8'), 'REDEDGE1': image.select('B5')}
                ).rename('CIRE'),
                'DWSI': image.expression(
                    'SWIR1 / NIR',
                    {'SWIR1': image.select('B11'), 'NIR': image.select('B8')}
                ).rename('DWSI'),
                'GCVI': image.expression(
                    '(NIR / GREEN) - 1',
                    {'NIR': image.select('B8'), 'GREEN': image.select('B3')}
                ).rename('GCVI'),
                'MCARI': image.expression(
                    '((REDEDGE1 - RED) - 0.2 * (REDEDGE1 - GREEN)) * (REDEDGE1 / RED)',
                    {'REDEDGE1': image.select('B5'), 'RED': image.select('B4'), 'GREEN': image.select('B3')}
                ).rename('MCARI'),
                'SIPI': image.expression(
                    '(NIR - BLUE) / (NIR - RED)',
                    {'NIR': image.select('B8'), 'BLUE': image.select('B2'), 'RED': image.select('B4')}
                ).rename('SIPI')
            }
            return image.addBands(list(indices.values()))
        
        recent_image_with_indices = add_indices(recent_image)
        sample = recent_image_with_indices.sample(region=point, scale=10, numPixels=1).first()
        sample_data = sample.getInfo().get('properties', {})

        index_data = {
            'NDVI': sample_data.get('NDVI', 'N/A'),
            'EVI': sample_data.get('EVI', 'N/A'),
            'ARI': sample_data.get('ARI', 'N/A'),
            'CAI': sample_data.get('CAI', 'N/A'),
            'CIRE': sample_data.get('CIRE', 'N/A'),
            'DWSI': sample_data.get('DWSI', 'N/A'),
            'GCVI': sample_data.get('GCVI', 'N/A'),
            'MCARI': sample_data.get('MCARI', 'N/A'),
            'SIPI': sample_data.get('SIPI', 'N/A'),
            "timestamp": datetime.datetime.utcnow()
        }

        # Check if the latest data is new or if it needs to be updated
        latest_db_data = gee_collection.find_one(sort=[("timestamp", -1)])
        if not latest_db_data or latest_db_data['timestamp'] != index_data['timestamp']:
            gee_collection.insert_one(index_data)
            print(f"Google Earth Engine data stored in MongoDB: {index_data}")
        else:
            print("No new GEE data to store.")
    except Exception as e:
        print(f"GEE data fetch/store error: {e}")

# Initialize scheduler
scheduler = BackgroundScheduler()

# Schedule tasks
scheduler.add_job(fetch_and_store_thingspeak_data, 'interval', hours=1)
scheduler.add_job(fetch_and_store_nasa_data, 'interval', days=1)
scheduler.add_job(fetch_and_store_gee_data, 'interval', days=1)

# Start the scheduler
scheduler.start()

from flask import Response
from bson.json_util import dumps

@app.route('/view_thingspeak', methods=['GET'])
def view_thingspeak_data():
    data = thingspeak_collection.find_one(sort=[("timestamp", -1)])
    return Response(dumps(data), mimetype='application/json') if data else jsonify({'status': 'No data found'})

@app.route('/view_nasa', methods=['GET'])
def view_nasa_data():
    data = nasa_collection.find_one(sort=[("timestamp", -1)])
    return Response(dumps(data), mimetype='application/json') if data else jsonify({'status': 'No data found'})

@app.route('/view_gee', methods=['GET'])
def view_gee_data():
    data = gee_collection.find_one(sort=[("timestamp", -1)])
    return Response(dumps(data), mimetype='application/json') if data else jsonify({'status': 'No data found'})
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
    fetch_and_store_thingspeak_data()
    fetch_and_store_nasa_data()
    fetch_and_store_gee_data()

    # Start the Flask application
    app.run(debug=True, host='0.0.0.0', port=5000)
