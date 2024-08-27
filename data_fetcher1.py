import requests
import pandas as pd
#base_url="https://power.larc.nasa.gov/api/temporal/daily/point?start=20230101&end=20230101&latitude=31.0741&longitude=76.0232&community=re&parameters=T2M%2CRH2M%2CPS&format=json&header=true&time-standard=lst"

def fetch_data1(base_url):
    response = requests.get(base_url)
    if response.status_code == 200:
        data = response.json()
        parameters=data["properties"]["parameter"]        
        data_dict={ 
        "T2M":parameters.get("T2M",{}).get("20240729"),
        "RH2M":parameters.get("RH2M",{}).get("20240729"),
        "PS":parameters.get("PS",{}).get("20240729")
                 }
        
        return data_dict                       
    

    else:
        raise Exception(f"Failed to retrieve data. Status code: {response.status_code}")

