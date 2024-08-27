import requests

def fetch_data(api_url):
    response = requests.get(api_url)
    if response.status_code == 200:
        data = response.json()
        if "feeds" in data and len(data["feeds"]) > 1:
            field1_data_npk = data["feeds"][1].get("field4", "No Sensor data")#make this back to 4
            return {"field4": field1_data_npk}#make this back to 4
        else:
            raise Exception("Not enough data")

    else:
        raise Exception(f"Failed to retrieve data. Status code: {response.status_code}")
