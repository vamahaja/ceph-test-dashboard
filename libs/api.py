import streamlit as st
import requests
from utils.config import get_base_url

@st.cache_data(ttl=60)
def fetch_api_data(endpoint):
    """Fetch data from the Paddles API with basic error handling."""
    url = f"{get_base_url().rstrip('/')}{endpoint}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            st.warning(f"Data not found at {url}. (404)")
            return None
        else:
            st.error(f"Failed to fetch data. Status code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"Connection error: {e}")
        return None
