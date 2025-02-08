
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
file_path = 'Final_model_iguess.pkl'
with open(file_path, 'rb') as model_file:
    model = pickle.load(model_file)

import ee
import datetime

# Initialize Earth Engine
service_account = 'sargun@sargun20.iam.gserviceaccount.com'
key_file = 'sargun20-af558cd29ee0.json'
credentials = ee.ServiceAccountCredentials(service_account, key_file)
ee.Initialize(credentials)

# Configuration
sentinel2_collection = 'COPERNICUS/S2'

def get_recent_indices(lat=30.91028, lon=75.81886, radius=2, days_back=30):
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

        # Check if images are available
        if s2.size().getInfo() == 0:
            return None, 'No images found for the specified location and date range.'

        # Get the most recent image
        recent_image = s2.first()

        # Scale Sentinel-2 reflectance values
        scale_factor = 10000.0  # Sentinel-2 reflectance is stored as integers (0-10000)
        recent_image = recent_image.divide(scale_factor)

        # Function to calculate indices
        def add_indices(image):
            NIR = image.select('B8')
            RED = image.select('B4')
            GREEN = image.select('B3')
            BLUE = image.select('B2')
            RED_EDGE = image.select('B5')
            SWIR1 = image.select('B11')
            SWIR2 = image.select('B12')

            indices = {
                'NDVI': NIR.subtract(RED).divide(NIR.add(RED)).rename('NDVI'),
                'EVI': image.expression(
                    '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1.0001))',  # Avoid div by zero
                    {'NIR': NIR, 'RED': RED, 'BLUE': BLUE}
                ).rename('EVI'),
                'ARI': image.expression(
                    '(1 / GREEN) - (1 / RED_EDGE)',
                    {'GREEN': GREEN, 'RED_EDGE': RED_EDGE}
                ).rename('ARI'),
                'CAI': image.expression(
                    '0.5 * ((SWIR1 + SWIR2) - NIR)',
                    {'SWIR1': SWIR1, 'SWIR2': SWIR2, 'NIR': NIR}
                ).rename('CAI'),
                'CIRE': NIR.divide(RED_EDGE).subtract(1).rename('CIRE'),
                'DWSI': NIR.divide(SWIR1).rename('DWSI'),
                'GCVI': NIR.divide(GREEN).subtract(1).rename('GCVI'),
                'MCARI': image.expression(
                    '((RED_EDGE - RED) - 0.2 * (RED_EDGE - GREEN)) * (RED_EDGE / RED)',
                    {'RED_EDGE': RED_EDGE, 'RED': RED, 'GREEN': GREEN}
                ).rename('MCARI'),
                'SIPI': image.expression(
                    '(NIR - BLUE) / (NIR - RED)',
                    {'NIR': NIR, 'BLUE': BLUE, 'RED': RED}
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

        # Get index values
        indices_dict = sample.toDictionary().getInfo()
        return indices_dict

    except Exception as e:
        return None, str(e)

# Example Call
lat, lon, radius = 30.21813, 76.40966, 10
indices = get_recent_indices(lat, lon, radius)
print("Final Indices:", indices)