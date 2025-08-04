import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
import time
import logging
import streamlit as st
import json
import requests
import asyncio
import os 
from dotenv import load_dotenv
load_dotenv()



logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def extract_sebi_circulars_on_page(page_number: int) -> pd.DataFrame:
    """
    Extracts circulars from a specific page number on the SEBI website.

    This function navigates to the SEBI circulars page and then navigates
    to the specified page number by clicking 'Next' repeatedly if necessary.
    It then scrapes the date, title, and link for circulars on that specific page.

    Args:
        page_number (int): The specific page number to extract circulars from.
                            Must be a positive integer (page 1 is the first page).

    Returns:
        pd.DataFrame: A Pandas DataFrame where each row represents a circular
                        with 'Date', 'Title', and 'Link' columns from the
                        specified page. Returns an empty DataFrame if the page is
                        invalid or extraction fails.
    """
    if page_number <= 0:
        logging.warning("Page number must be a positive integer.")
        return pd.DataFrame()

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except WebDriverException as e:
        logging.error(f"Failed to initialize WebDriver: {e}")
        st.error("Failed to initialize WebDriver. This often happens in cloud environments without proper browser setup. Please ensure Google Chrome is available.")
        return pd.DataFrame()
    
    url = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0"
    logging.info(f"Navigating to URL: {url}")
    driver.get(url)

    extracted_data = []
    current_page = 1

    
    while current_page < page_number:
        try:
            old_table_element = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, 'sample_1'))
            )
            
            next_button_xpath = "//a[@title='Next']"
            next_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, next_button_xpath))
            )
            
            driver.execute_script("arguments[0].click();", next_button)
            logging.info(f"Clicked 'Next' button. Navigating to page {current_page + 1}.")
            
            WebDriverWait(driver, 15).until(EC.staleness_of(old_table_element))
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, 'sample_1')))
            
            current_page += 1
        except (NoSuchElementException, TimeoutException, StaleElementReferenceException) as e:
            logging.warning(f"Could not find 'Next' button or reached end of pages before reaching page {page_number}. Current page: {current_page}. Error: {e}")
            if driver:
                driver.quit()
            st.warning(f"Could not reach page {page_number}. The page may not exist or the 'Next' button could not be found.")
            return pd.DataFrame()

    
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, 'sample_1'))
        )
        logging.info(f"On target page {page_number}. Starting extraction...")
    except TimeoutException:
        logging.error(f"Timed out waiting for the circulars table to load on page {page_number}.")
        if driver:
            driver.quit()
        st.error("Timed out waiting for the circulars table to load.")
        return pd.DataFrame()

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    table = soup.find('table', id='sample_1')
    if not table:
        logging.warning(f"Could not find the data table (ID 'sample_1') on page {page_number}. Exiting.")
        if driver:
            driver.quit()
        st.warning("Could not find the data table on the SEBI website. The page structure may have changed.")
        return pd.DataFrame()
        
    rows = table.find('tbody').find_all('tr')
    
    if not rows:
        logging.info(f"No rows found on page {page_number}. This might be an empty page.")
        if driver:
            driver.quit()
        st.info("No circulars found on this page.")
        return pd.DataFrame()

    for row in rows:
        cells = row.find_all('td')
        if len(cells) == 2:
            date = cells[0].text.strip()
            link_tag = cells[1].find('a') 
            if link_tag:
                title = link_tag.get('title', link_tag.text.strip())
                link = link_tag.get('href')
                
                if link and not link.startswith(('http://', 'https://')):
                    base_url = "https://www.sebi.gov.in"
                    link = base_url + link
                
                extracted_data.append({
                    "Date": date,
                    "Title": title,
                    "Link": link
                })

    if driver:
        driver.quit()
    
    return pd.DataFrame(extracted_data)

def get_circular_text_from_link(link: str) -> str:
    """
    Navigates to a circular's link and extracts its main text content.

    Args:
        link (str): The URL of the circular.

    Returns:
        str: The extracted text content, or an empty string if extraction fails.
    """
    driver = None
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        logging.info(f"Navigating to circular link for text extraction: {link}")
        driver.get(link)
        
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, 'body'))
        )
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        
        content_div = soup.find('div', class_='main_full') 
        
        text = ""
        if content_div:
            
            paragraphs = content_div.find_all('p')
            text = "\n".join([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])
            if not text: 
                text = content_div.get_text(separator='\n', strip=True)
        else:
            
            text = soup.body.get_text(separator='\n', strip=True)
            
        return text
    except Exception as e:
        logging.error(f"Error extracting text from {link}: {e}")
        return ""
    finally:
        if driver:
            driver.quit()

async def summarize_circular_text(circular_text: str, circular_link: str) -> str:
    """
    Summarizes the given circular text using the Gemini API.

    Args:
        circular_text (str): The full text of the circular to summarize.
        circular_link (str): The URL of the circular to include in the summary.

    Returns:
        str: The summarized text from the Gemini API, or an error message.
    """
    if not circular_text.strip():
        return "Please provide text to summarize."

    
    prompt = (
        f"Provide a detailed and effective summary of the following SEBI circular. "
        f"The summary should cover all key aspects, new regulations, guidelines, important dates, "
        f"and affected stakeholders. Ensure the summary is coherent, professional, and suitable "
        f"for official communication. The summary must not exceed 1000 words.\n\n"
        f"Circular Text:\n{circular_text}"
    )
    
    chat_history = [{"role": "user", "parts": [{"text": prompt}]}]
    payload = {"contents": chat_history}

   
    api_key = os.getenv("Api_Key")
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}" 

    try:
        response = requests.post(api_url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        response.raise_for_status() 
        result = response.json()

        if result.get('candidates') and len(result['candidates']) > 0 and \
           result['candidates'][0].get('content') and result['candidates'][0]['content'].get('parts') and \
           len(result['candidates'][0]['content']['parts']) > 0:
            summary_text = result['candidates'][0]['content']['parts'][0].get('text', 'No summary text found.')
            
            return f"{summary_text}\n\n[Original Circular Link]({circular_link})"
        else:
            logging.error(f"Gemini API response structure unexpected: {result}")
            return "Failed to get summary: Unexpected API response structure."
    except requests.exceptions.RequestException as e:
        logging.error(f"Error calling Gemini API: {e}")
        return f"An error occurred while summarizing: {e}"
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON response from Gemini API: {e}")
        return f"An error occurred while processing API response: {e}"
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return f"An unexpected error occurred: {e}"



st.set_page_config(page_title="SEBI Circulars", layout="wide")

st.title("SEBI Circulars Extractor & Summarizer ")
st.markdown("---")

st.write("""
This application extracts circulars from a specific page of the SEBI website, then provide a detailed summary of the selected circular.
""")

if 'extracted_df' not in st.session_state:
    st.session_state['extracted_df'] = pd.DataFrame()
if 'summary_output' not in st.session_state:
    st.session_state['summary_output'] = ""


def run_extraction():
    st.session_state['summary_output'] = "" 
    st.session_state['extracted_df'] = extract_sebi_circulars_on_page(st.session_state.page_number)
    if not st.session_state['extracted_df'].empty:
        st.success("Extraction complete. Please select a circular from the dropdown to summarize.")
    else:
        st.warning("No circulars found on this page or an error occurred during extraction.")


async def run_summarization():
    selected_title_with_date = st.session_state.circular_selection
    if not selected_title_with_date or st.session_state['extracted_df'].empty:
        st.error("Please select a circular and ensure data is extracted first.")
        return

    try:
        parts = selected_title_with_date.split(' - ', 1)
        selected_date = parts[0].strip()
        selected_title = parts[1].strip()
    except IndexError:
        st.error("Invalid circular selection format. Please re-extract circulars.")
        return

    selected_row = st.session_state['extracted_df'][(st.session_state['extracted_df']['Title'] == selected_title) & (st.session_state['extracted_df']['Date'] == selected_date)]
    
    if selected_row.empty:
        st.error("Selected circular not found in the extracted data. Please re-extract circulars.")
        return
    
    circular_link = selected_row['Link'].iloc[0]
    
    circular_text = get_circular_text_from_link(circular_link)
    if not circular_text.strip():
        st.error("Could not extract text from the circular link. The content might be a PDF or the page structure changed.")
        return
    
    with st.spinner("Summarizing the circular..."):
        summary = await summarize_circular_text(circular_text, circular_link)
        st.session_state['summary_output'] = summary




st.header("1. Extract Circulars from a Page")
page_number = st.number_input(
    "Enter Page Number (1-108)", 
    min_value=1, 
    max_value=108, 
    value=1, 
    step=1, 
    key='page_number'
)

st.button("Extract Circulars", on_click=run_extraction)

st.markdown("---")

if not st.session_state['extracted_df'].empty:
    st.header("2. Select a Circular and Summarize")
    circular_options = [f"{row['Date']} - {row['Title']}" for index, row in st.session_state['extracted_df'].iterrows()]
    selected_circular = st.selectbox(
        "Select a Circular to summarize:",
        circular_options,
        key='circular_selection'
    )
    
    if st.button("Summarize Selected Circular"):
        asyncio.run(run_summarization())
    
    st.markdown("---")
    
    if st.session_state['summary_output']:
        st.header("Summary of Selected Circular")
        st.markdown(st.session_state['summary_output'])

