from flask import Flask, jsonify
from data_fetcher import fetch_data  
import numpy as np
import pickle
import requests
from data_fetcher1 import fetch_data1
import pandas as pd
import sklearn
import ee
from flask import request, send_file
import json
import datetime
import os

# Initialize Earth Engine
service_account = 'sargun@sargun20.iam.gserviceaccount.com'
key_file = 'sargun20-af558cd29ee0.json'
credentials = ee.ServiceAccountCredentials(service_account, key_file)
ee.Initialize(credentials)

# Configuration
sentinel2_collection = 'COPERNICUS/S2'

def get_recent_indices(lat, lon, radius, days_back=30):
    global last_valid_data2
    try:
        # Create a geometry
        point = ee.Geometry.Point([lon, lat])
        buffer = point.buffer(radius * 1000)  # Convert radius to meters

        # Calculate start and end dates
        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=days_back)

        # Load Sentinel-2 image collection and filter by recent dates
        s2 = ee.ImageCollection(sentinel2_collection) \
            .filterBounds(buffer) \
            .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')) \
            .sort('system:time_start', False)  # Sort by date, newest first

        # Print the count of images found
        image_count = s2.size().getInfo()
        print(f"Number of images found: {image_count}")

        # Check if there are images available
        if image_count == 0:
            return None, 'No images found for the specified location and date range.'

        # Get the most recent image
        recent_image = s2.first()

        # Function to calculate indices for an image
        def add_indices(image):
            indices = {
                'NDVI': image.normalizedDifference(['B8', 'B4']).rename('NDVI'),
                'EVI': image.expression(
                    '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
                    {
                        'NIR': image.select('B8'),
                        'RED': image.select('B4'),
                        'BLUE': image.select('B2')
                    }
                ).rename('EVI'),
                'ARI': image.expression(
                    '(1 / GREEN) - (1 / RED_EDGE)',
                    {
                        'GREEN': image.select('B3'),
                        'RED_EDGE': image.select('B5')
                    }
                ).rename('ARI'),
                'CAI': image.expression(
                    '0.5 * (SWIR1 + SWIR2) - NIR',
                    {
                        'SWIR1': image.select('B11'),
                        'SWIR2': image.select('B12'),
                        'NIR': image.select('B8')
                    }
                ).rename('CAI'),
                'CIRE': image.expression(
                    '(NIR / RED_EDGE) - 1',
                    {
                        'NIR': image.select('B8'),
                        'RED_EDGE': image.select('B5')
                    }
                ).rename('CIRE'),
                'DWSI': image.expression(
                    'NIR / SWIR',
                    {
                        'NIR': image.select('B8'),
                        'SWIR': image.select('B11')
                    }
                ).rename('DWSI'),
                'GCVI': image.expression(
                    '(NIR / GREEN) - 1',
                    {
                        'NIR': image.select('B8'),
                        'GREEN': image.select('B3')
                    }
                ).rename('GCVI'),
                'MCARI': image.expression(
                    '((RED_EDGE - RED) - 0.2 * (RED_EDGE - GREEN)) * (RED_EDGE / RED)',
                    {
                        'RED_EDGE': image.select('B5'),
                        'RED': image.select('B4'),
                        'GREEN': image.select('B3')
                    }
                ).rename('MCARI'),
                'SIPI': image.expression(
                    '(NIR - BLUE) / (NIR - RED)',
                    {
                        'NIR': image.select('B8'),
                        'BLUE': image.select('B2'),
                        'RED': image.select('B4')
                    }
                ).rename('SIPI')
            }
            return image.addBands(list(indices.values()))

        # Apply index calculations to the most recent image
        recent_image_with_indices = add_indices(recent_image)

        # Sample a single point for the index data
        sample = recent_image_with_indices.sample(
            region=point,
            scale=10,
            numPixels=1
        ).first()

        # Get the data from the sample
        sample_data = sample.getInfo()
        properties = sample_data['properties']

        # Check if properties were sampled
        if not properties:
            return None, 'No sample data found for the specified location and radius.'

        # Convert the properties to a dictionary
        index_values = {
            'NDVI': properties.get('NDVI', 'N/A'),
            'EVI': properties.get('EVI', 'N/A'),
            'ARI': properties.get('ARI', 'N/A'),
            'CAI': properties.get('CAI', 'N/A'),
            'CIRE': properties.get('CIRE', 'N/A'),
            'DWSI': properties.get('DWSI', 'N/A'),
            'GCVI': properties.get('GCVI', 'N/A'),
            'MCARI': properties.get('MCARI', 'N/A'),
            'SIPI': properties.get('SIPI', 'N/A')
        }
        last_valid_data2=index_values

        # Create a JSON file from the data
        json_file = 'indices_data.json'
        with open(json_file, 'w') as f:
            json.dump(index_values, f)

        return index_values, json_file, None

    except Exception as e:
        print(f"Error: {e}")
        return None, None, str(e)




app = Flask(__name__)
base_url="https://power.larc.nasa.gov/api/temporal/daily/point?start=20240729&end=20240729&latitude=31.0741&longitude=76.0232&community=re&parameters=T2M%2CRH2M%2CPS&format=json&header=true&time-standard=lst"


API_URL = 'https://api.thingspeak.com/channels/2187169/feeds.json?api_key=LELEVX9B3SDHSFZ9&results=300'
last_valid_data = None

file_path = 'final_model_iguess.pkl'

if not os.path.exists(file_path):
    print(f"Error: The file {file_path} does not exist.")
else:
    with open(file_path, 'rb') as model_file:
        model = pickle.load(model_file)

@app.route('/')
def index():
    return jsonify({'message': 'Hello, world!'})


@app.route('/fetch', methods=['GET'])
def fetch():
    global last_valid_data
    

    try:
        data = fetch_data(API_URL)
        if 'field4' in data and data['field4'] != '//////':#make this back to 4 in both places
        #        and data['field4'] != '655.35/655.35/255.00/6553.50/65535.00/65535.00/65535.00':
            field1_values = data['field4'].split('/')#make this back to 4
            columns = ['hp1', 'm1', 't1', 'c1', 'n1', 'p1', 'k1']
            data_dict = {var: float(val) for var, val in zip(columns, field1_values)}

            last_valid_data = data_dict
        else:
            if last_valid_data is None:
                raise Exception("No valid data available")
            data_dict = last_valid_data

        return jsonify(data_dict)
    except Exception as e:
        return jsonify({"Error": str(e)}), 500
    

@app.route('/fetch_data',methods=["GET"])
def fetch1():
    global last_valid_data1
    satellite_dict=fetch_data1(base_url)
    last_valid_data1=satellite_dict
    return jsonify(satellite_dict)  
        

@app.route('/prediction', methods=['GET'])
def predict():
    try:
        if last_valid_data is None:
            raise Exception("No valid data available from /fetch endpoint")

        data_dict = last_valid_data
        satellite_dict = last_valid_data1
        gee_dict=last_valid_data2
        
        
        missing_keys = [key for key in ['T2M', 'RH2M', 'PS'] if key not in satellite_dict]
        if missing_keys:
            
            raise Exception(f"Missing data in satellite_dict: {', '.join(missing_keys)}")

        
        hp_t_c_array = np.array([
            satellite_dict.get('T2M'),  
            satellite_dict.get('RH2M'),
            satellite_dict.get('PS'),
            gee_dict.get('ARI'),
            gee_dict.get('CAI'),
            gee_dict.get('CIRE'),
            gee_dict.get('DWSI'),
            gee_dict.get('EVI'),
            gee_dict.get('GCVI'),
            gee_dict.get('MCARI'),            
            gee_dict.get('SIPI'),
            data_dict.get('hp1'),
            data_dict.get('t1'),
            data_dict.get('c1')
            
        ])
        predict_data=pd.DataFrame([hp_t_c_array])

        prediction = model.predict(predict_data.loc[[0]])  # Reshape to 2D

        return jsonify({"Prediction": prediction.tolist()},hp_t_c_array.tolist())
    except Exception as e:
        return jsonify({"Error": str(e)}), 500
@app.route('/gee', methods=['GET'])
def get_recent_indices_route():
    try:
        global last_valid_data2
        # Permanently set latitude, longitude, and radius
        lat = 30.21813
        lon = 76.40966
        radius = 10
        days_back = int(request.args.get('days_back', 30))  # Default to 30 days

        # Debugging prints
        print("Using permanent latitude, longitude, and radius:")
        print(f"Latitude: {lat}")
        print(f"Longitude: {lon}")
        print(f"Radius: {radius}")
        print(f"Days back: {days_back}")

        index_values, json_file, error = get_recent_indices(lat, lon, radius, days_back)
        last_valid_data2=index_values

        if error:
            return jsonify({'error': error}), 500

        # Return the results as JSON response
        return jsonify(index_values)

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
