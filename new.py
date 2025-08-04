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
import gradio as gr
import json
import requests
import asyncio
import re # For regular expressions in local search
import streamlit as st
import os 

from dotenv import load_dotenv
load_dotenv()

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper for WebDriver initialization ---
def initialize_driver():
    """Initializes and returns a headless Chrome WebDriver."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36")
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except WebDriverException as e:
        logging.error(f"Failed to initialize WebDriver: {e}")
        logging.error("This might be due to Chrome browser not being correctly installed or accessible in this environment. "
                      "Please ensure Google Chrome is available on the system where this script is executed.")
        return None


def extract_sebi_circulars_on_page(page_number: int) -> pd.DataFrame:
    """
    Extracts circulars from a specific page number on the SEBI website.
    This function is now mainly used by `scrape_recent_circulars` to get a single page.
    """
    if page_number <= 0:
        logging.warning("Page number must be a positive integer.")
        return pd.DataFrame()

    driver = initialize_driver()
    if not driver:
        return pd.DataFrame()

    url = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0"
    logging.info(f"Navigating to URL: {url} to reach page {page_number}")
    driver.get(url)

    extracted_data = []
    current_page = 1

    # Navigate to the target page by clicking 'Next'
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
            return pd.DataFrame()

    # Once on the target page, extract data
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, 'sample_1'))
        )
        logging.info(f"On target page {page_number}. Starting extraction...")
    except TimeoutException:
        logging.error(f"Timed out waiting for the circulars table to load on page {page_number}.")
        if driver:
            driver.quit()
        return pd.DataFrame()

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    table = soup.find('table', id='sample_1')
    if not table:
        logging.warning(f"Could not find the data table (ID 'sample_1') on page {page_number}. Exiting.")
        if driver:
            driver.quit()
        return pd.DataFrame()

    rows = table.find('tbody').find_all('tr')

    if not rows:
        logging.info(f"No rows found on page {page_number}. This might be an empty page.")
        if driver:
            driver.quit()
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

# --- NEW FUNCTION: scrape_recent_circulars ---
def scrape_recent_circulars(num_pages: int = 10) -> pd.DataFrame:
    """
    Scrapes circulars from the first `num_pages` of the SEBI website.
    This creates the local dataset for "similar circulars" search.
    """
    if num_pages <= 0:
        logging.warning("Number of pages to scrape must be positive.")
        return pd.DataFrame()

    logging.info(f"Starting to scrape circulars from the first {num_pages} pages...")
    all_circulars_data = pd.DataFrame()

    driver = initialize_driver()
    if not driver:
        return pd.DataFrame()

    url = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0"
    driver.get(url)

    for page_idx in range(1, num_pages + 1):
        logging.info(f"Scraping page {page_idx}...")
        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, 'sample_1')))
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            table = soup.find('table', id='sample_1')

            if not table:
                logging.warning(f"Could not find table on page {page_idx}. Stopping multi-page scrape.")
                break

            rows = table.find('tbody').find_all('tr')
            page_data = []
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
                        page_data.append({"Date": date, "Title": title, "Link": link})

            all_circulars_data = pd.concat([all_circulars_data, pd.DataFrame(page_data)], ignore_index=True)
            logging.info(f"Successfully scraped {len(page_data)} circulars from page {page_idx}.")

            if page_idx < num_pages:
                next_button_xpath = "//a[@title='Next']"
                try:
                    old_table_element = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, 'sample_1')))
                    next_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, next_button_xpath)))
                    driver.execute_script("arguments[0].click();", next_button)
                    WebDriverWait(driver, 15).until(EC.staleness_of(old_table_element))
                    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, 'sample_1')))
                except (NoSuchElementException, TimeoutException, StaleElementReferenceException) as e:
                    logging.info(f"No 'Next' button found or end of pages reached at page {page_idx}. Stopping multi-page scrape. Error: {e}")
                    break

        except TimeoutException:
            logging.error(f"Timed out waiting for circulars table on page {page_idx}. Stopping multi-page scrape.")
            break
        except Exception as e:
            logging.error(f"An unexpected error occurred while scraping page {page_idx}: {e}")
            break
    if driver:
        driver.quit()
    
    # Remove duplicates based on Link (in case same circular appears on multiple pages due to pagination quirks)
    all_circulars_data.drop_duplicates(subset=['Link'], inplace=True)
    logging.info(f"Finished scraping. Total unique circulars scraped: {len(all_circulars_data)}")
    return all_circulars_data

# --- Existing Function: get_circular_text_from_link (No changes) ---
def get_circular_text_from_link(link: str) -> str:
    """
    Navigates to a circular's link and extracts its main text content.
    """
    driver = None
    try:
        driver = initialize_driver()
        if not driver:
            return ""

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

# --- Existing Function: summarize_circular_text 
async def summarize_circular_text(circular_text: str, circular_link: str) -> str:
    """
    Summarizes the given circular text using the Gemini API.
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

# --- Existing Function: extract_key_terms_from_title (No changes) ---
async def extract_key_terms_from_title(title: str) -> str:
    """
    Extracts comma-separated key terms from a circular title using the Gemini API.
    """
    if not title.strip():
        return "No title provided for key term extraction."

    prompt = (
        f"Extract comma-separated key terms from the following SEBI circular title. "
        f"Focus on the most important keywords that describe the subject matter. "
        f"For example, if the title is 'Framework for Short Selling', key terms could be 'Short Selling, Framework'."
        f"\n\nTitle: {title}"
        f"\n\nKey Terms:"
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
            key_terms = result['candidates'][0]['content']['parts'][0].get('text', 'No key terms found.')
            return key_terms
        else:
            logging.error(f"Gemini API response structure unexpected for key term extraction: {result}")
            return "Failed to get key terms: Unexpected API response structure."
    except requests.exceptions.RequestException as e:
        logging.error(f"Error calling Gemini API for key term extraction: {e}")
        return f"An error occurred while extracting key terms: {e}"
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON response from Gemini API for key term extraction: {e}")
        return f"An error occurred while processing API response for key terms: {e}"
    except Exception as e:
        logging.error(f"An unexpected error occurred during key term extraction: {e}")
        return f"An unexpected error occurred during key term extraction: {e}"

# --- NEW FUNCTION: find_similar_circulars_local ---
def find_similar_circulars_local(keywords_str: str, all_circulars_df: pd.DataFrame, original_title: str) -> pd.DataFrame:
    """
    Performs a local search within the scraped DataFrame for circulars whose titles
    contain any of the given keywords. Excludes the original circular.
    """
    if all_circulars_df.empty or not keywords_str.strip():
        return pd.DataFrame()

    keywords = [k.strip().lower() for k in keywords_str.split(',') if k.strip()]
    if not keywords:
        return pd.DataFrame()

    logging.info(f"Searching for similar circulars with keywords: {keywords}")
    similar_df = pd.DataFrame()

    # Create a regex pattern to match any of the keywords
    # Use word boundaries to match whole words and escape special characters
    pattern = r'\b(?:' + '|'.join(re.escape(k) for k in keywords) + r')\b'

    # Filter the DataFrame based on the regex pattern in the 'Title' column
    # Also ensure it's not the original circular itself
    similar_df = all_circulars_df[
        (all_circulars_df['Title'].str.lower().str.contains(pattern, na=False, regex=True)) &
        (all_circulars_df['Title'].str.strip() != original_title.strip()) # Exclude the original circular
    ].copy() # Use .copy() to avoid SettingWithCopyWarning

    # Sort by date (most recent first) and then by title
    similar_df['Date_Parsed'] = pd.to_datetime(similar_df['Date'], format='%d %b %Y', errors='coerce')
    similar_df.sort_values(by=['Date_Parsed', 'Title'], ascending=[False, True], inplace=True)
    similar_df.drop(columns=['Date_Parsed'], inplace=True, errors='ignore') # Clean up temp column

    logging.info(f"Found {len(similar_df)} similar circulars locally.")
    return similar_df

# --- Modified Function: process_selected_circular (to trigger similar circulars search) ---
async def process_selected_circular(selected_title_with_date: str, extracted_df: pd.DataFrame, all_circulars_df_state: pd.DataFrame) -> tuple[str, gr.update, gr.update]:
    """
    Processes the selected circular: extracts its text, summarizes it,
    and then finds and populates similar circulars.
    """
    if not selected_title_with_date or extracted_df.empty:
        return "Please select a circular and ensure data is extracted first.", gr.update(visible=False), gr.update(visible=False)

    try:
        parts = selected_title_with_date.split(' - ', 1)
        selected_date = parts[0].strip()
        selected_title = parts[1].strip()
    except IndexError:
        return "Invalid circular selection format. Please re-extract circulars.", gr.update(visible=False), gr.update(visible=False)

    selected_row = extracted_df[(extracted_df['Title'] == selected_title) & (extracted_df['Date'] == selected_date)]

    if selected_row.empty:
        return "Selected circular not found in the extracted data. Please re-extract circulars.", gr.update(visible=False), gr.update(visible=False)

    circular_link = selected_row['Link'].iloc[0]

    circular_text = get_circular_text_from_link(circular_link)
    if not circular_text.strip():
        return "Could not extract text from the circular link. The content might be a PDF or the page structure changed.", gr.update(visible=False), gr.update(visible=False)

    summary = await summarize_circular_text(circular_text, circular_link)

    # --- Find Similar Circulars ---
    key_terms = await extract_key_terms_from_title(selected_title)
    similar_circulars_df = find_similar_circulars_local(key_terms, all_circulars_df_state, selected_title) # Pass original title to exclude

    similar_dropdown_choices = [f"{row['Date']} - {row['Title']}" for index, row in similar_circulars_df.iterrows()]
    similar_dropdown_update = gr.update(
        choices=similar_dropdown_choices,
        value=None,
        visible=True
    ) if not similar_circulars_df.empty else gr.update(visible=False, choices=[], value=None)

    similar_status_update = gr.update(
        value=f"<p style='color:green;'>Found {len(similar_circulars_df)} similar circulars based on keywords: {key_terms}.</p>" if not similar_circulars_df.empty else "<p style='color:orange;'>No similar circulars found based on extracted keywords.</p>",
        visible=True
    )

    return summary, similar_dropdown_update, similar_status_update

# --- NEW FUNCTION: process_selected_similar_circular ---
async def process_selected_similar_circular(selected_title_with_date: str, all_circulars_df: pd.DataFrame) -> str:
    """
    Processes the selected similar circular: extracts its text and summarizes it.
    """
    if not selected_title_with_date or all_circulars_df.empty:
        return "Please select a similar circular."

    try:
        parts = selected_title_with_date.split(' - ', 1)
        selected_date = parts[0].strip()
        selected_title = parts[1].strip()
    except IndexError:
        return "Invalid similar circular selection format."

    selected_row = all_circulars_df[(all_circulars_df['Title'] == selected_title) & (all_circulars_df['Date'] == selected_date)]

    if selected_row.empty:
        return "Selected similar circular not found in the pre-scraped data."

    circular_link = selected_row['Link'].iloc[0]

    circular_text = get_circular_text_from_link(circular_link)
    if not circular_text.strip():
        return "Could not extract text from the similar circular link. The content might be a PDF or the page structure changed."

    summary = await summarize_circular_text(circular_text, circular_link)
    return summary

# Helper function to extract and display key terms for all titles on a page
# We are intentionally making this helper not return anything to be displayed directly in the UI.
# It's kept for potential debugging or future features if you decide to show key terms.
async def extract_and_display_key_terms_async(df: pd.DataFrame) -> str:
    """
    Asynchronously extracts and formats key terms for all circulars in the DataFrame.
    (This function will now primarily serve for logging or internal use, not direct UI display).
    """
    if df.empty:
        return ""

    all_key_terms_list = []
    tasks = [extract_key_terms_from_title(row['Title']) for index, row in df.iterrows()]
    key_terms_results = await asyncio.gather(*tasks)

    for i, row in df.iterrows():
        title = row['Title']
        key_terms = key_terms_results[i]
        if key_terms and "Failed to get key terms" not in key_terms:
            all_key_terms_list.append(f"**{title}**: {key_terms}")
        else:
            all_key_terms_list.append(f"**{title}**: Could not extract key terms.")
    
    # Log the key terms for debugging/information, but don't return for UI display here.
    logging.info("Generated key terms:\n" + "\n".join(all_key_terms_list))
    return "" # Return empty string as we don't want to display it in the UI directly

# Define the async function for updating outputs separately
async def update_extraction_outputs(df, page_num):
    """
    Handles updating Gradio outputs after circular extraction.
    This function is async because it calls another async function (extract_and_display_key_terms_async).
    """
    # Update dropdown and navigation status
    dropdown_update = gr.update(
        choices=[f"{row['Date']} - {row['Title']}" for index, row in df.iterrows()],
        value=None,
        visible=True
    ) if not df.empty else gr.update(visible=False, choices=[], value=None)

    status_update = gr.update(
        value=f"<p style='color:green;'>Extraction complete for page {page_num}. Please select a circular from the dropdown to summarize.</p>" if not df.empty else f"<p style='color:red;'>No circulars found on page {page_num} or an error occurred during extraction.</p>",
        visible=True
    )

    # Await the async function for key term extraction, but don't update key_terms_output with its return
    await extract_and_display_key_terms_async(df) # Call it, but don't use its return for UI

    # Keep key_terms_output hidden
    key_terms_update = gr.update(value="", visible=False) # Always set to invisible and clear value

    return [dropdown_update, status_update, key_terms_update]

# --- Streamlit ---
st.set_page_config(page_title="SEBI Circulars Extractor & Summarizer", layout="wide")
st.title("SEBI Circulars Extractor & Summarizer")
st.markdown("---")

# States (use session_state)
if 'extracted_df' not in st.session_state:
    st.session_state.extracted_df = pd.DataFrame()

if 'all_circulars_df' not in st.session_state:
    st.session_state.all_circulars_df = pd.DataFrame()

# Section: Load Recent Circulars
st.header("1. Load Recent Circulars for Similarity Search")
num_pages = st.number_input("Number of Pages to Scrape (1-108):", min_value=1, max_value=108, value=10)
if st.button("Load Recent Circulars"):
    with st.spinner("Scraping recent circulars..."):
        recent_df = scrape_recent_circulars(num_pages)
        st.session_state.all_circulars_df = recent_df
        st.success(f"Loaded {len(recent_df)} recent circulars.")

# Section: Extract Circulars from Specific Page
st.header("2. Extract Circulars from a Specific Page")
page_number = st.number_input("Enter Page Number (1-108):", min_value=1, max_value=108, value=1)
if st.button("Extract Circulars from Page"):
    with st.spinner("Extracting circulars from selected page..."):
        extracted_df = extract_sebi_circulars_on_page(page_number)
        st.session_state.extracted_df = extracted_df
        if not extracted_df.empty:
            st.success(f"Extracted {len(extracted_df)} circulars from page {page_number}.")
        else:
            st.error("No circulars found or an error occurred.")

# Section: Select and Summarize a Circular
st.header("3. Select and Summarize a Circular")
if not st.session_state.extracted_df.empty:
    choices = [f"{row['Date']} - {row['Title']}" for _, row in st.session_state.extracted_df.iterrows()]
    selected = st.selectbox("Choose a circular to summarize:", choices)
    if st.button("Summarize Selected Circular"):
        async def summarize_and_find_similar():
            with st.spinner("Processing and summarizing circular..."):
                summary, similar_choices, status_msg = await process_selected_circular(
                    selected,
                    st.session_state.extracted_df,
                    st.session_state.all_circulars_df
                )
                st.markdown("**Summary:**")
                st.markdown(summary, unsafe_allow_html=True)

                if "Found" in status_msg['value']:
                    st.markdown(status_msg['value'], unsafe_allow_html=True)
                    similar_selected = st.selectbox("Choose a similar circular:", similar_choices['choices'])
                    if st.button("Summarize Similar Circular"):
                        with st.spinner("Summarizing similar circular..."):
                            similar_summary = await process_selected_similar_circular(
                                similar_selected,
                                st.session_state.all_circulars_df
                            )
                            st.markdown("**Similar Circular Summary:**")
                            st.markdown(similar_summary, unsafe_allow_html=True)
                else:
                    st.warning("No similar circulars found.")

        asyncio.run(summarize_and_find_similar())
else:
    st.info("Please extract circulars first to summarize.")
