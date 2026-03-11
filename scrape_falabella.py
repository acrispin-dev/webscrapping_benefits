import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import pandas as pd
import time
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def scrape_falabella():
    # Try the 'todos' page which likely has a grid view
    url = "https://www.bancofalabella.pe/promociones/todos"
    print(f"Scraping Falabella ({url})...")
    
    chrome_options = Options()
    # chrome_options.add_argument("--headless") # Comment out headless for debugging if needed, but keeping it for now
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # Add reliable user-agent
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    all_promos = []
    
    try:
        driver.get(url)
        # Wait for hydration
        time.sleep(5)

        # Check for Modal and close it
        try:
            print("Checking for popups...")
            # Try to click the overlay (outside the banner) first as requested
            try:
                overlay = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "div[class*='ModalAdvertising_overlay']"))
                )
                print("Found overlay, clicking it...")
                overlay.click()
                print("Clicked overlay.")
                time.sleep(1)
            except:
                print("Overlay not clickable or found, trying close button...")
                # Fallback to close button if overlay fails
                close_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "div[class*='ModalAdvertising_icon-close']"))
                )
                close_btn.click()
                print("Clicked close button.")
            
            time.sleep(2)
        except Exception as e:
            print(f"No popup found or action failed: {e}")

        print("Page URL:", driver.current_url)
        
        # Verify we have the container
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[class*='BenefitsCard_cards-content']"))
            )
            print("Benefits container found.")
        except:
            print("Benefits container NOT found. Dumping source and exiting.")
            with open("src/falabella_debug_fail.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            return

        print("Starting infinite scroll...")
        
        last_height = driver.execute_script("return document.body.scrollHeight")
        no_change_count = 0
        
        while True:
            # Scroll down to bottom
            driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
            
            # Also try to scroll the React container if it exists
            driver.execute_script("""
                var nextDiv = document.getElementById('__next');
                if(nextDiv) { nextDiv.scrollTop = nextDiv.scrollHeight; }
            """)
            
            time.sleep(4) # Wait longer for network

            new_height = driver.execute_script("return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
            
            # Also check if number of cards increased
            soup_check = BeautifulSoup(driver.page_source, 'html.parser')
            card_count = len(soup_check.find_all('div', class_=lambda c: c and 'BenefitsCard_card' in c))
            print(f"Scrolled. Height: {new_height}. Card count: {card_count}")

            if new_height == last_height:
                no_change_count += 1
                if no_change_count >= 3:
                    if card_count > 100: # We expect around 146
                        print("Reached end of content.")
                        break
                    else:
                        print(f"Stuck at {card_count} cards. Resizing window to trigger reflow.")
                        driver.set_window_size(1920, 1080 + no_change_count * 100)
                        if no_change_count > 5:
                            break
            else:
                no_change_count = 0
                last_height = new_height
        
        print("Finished scrolling.")
        
        # Save debug HTML
        with open("src/falabella_debug.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
            
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # Updated selector based on debug HTML
        # Exclude 'cards-content' wrapper
        cards = soup.find_all('div', class_=lambda c: c and 'BenefitsCard_card' in c and 'cards-content' not in c)
            
        print(f"Found {len(cards)} potential card elements.")
        
        for card in cards:
            # Extract info
            
            # Extract Commerce Name from Logo (Title)
            title = "Falabella" # Default
            # Look for the logo image
            logo_img = card.find('img', class_=lambda c: c and 'NewCardBenefits_logo' in c)
            
            if logo_img:
                # Url often in srcset or src
                img_url = logo_img.get('srcset', '') or logo_img.get('src', '')
                
                # User pattern: card_logo_<name> or just logo_<name>
                # We need to capture the name after card_logo_ or logo_ until the next dot or question mark
                # Example: card_logo_kfc.svg -> kfc
                match = re.search(r'(?:card_)?logo_([^\.]+)', img_url)
                
                if match:
                    # Clean up the name
                    raw_name = match.group(1)
                    # Filter out if it captured query params accidentally (though regex says [^.]+)
                    # Sometimes files don't have extension and go straight to ?
                    if '?' in raw_name:
                        raw_name = raw_name.split('?')[0]
                        
                    title = raw_name.replace('_', ' ').replace('-', ' ').title()
                else:
                    # Fallback to alt tag if regex fails, but clean it
                    alt = logo_img.get('alt', '')   
                    if alt.startswith('logo-'):
                        title = alt.replace('logo-', '').strip()
                    else:
                         # If alt is long description, maybe better to leave it generic?
                         # For now, let's keep it if it's not too long
                         if len(alt) < 50:
                             title = alt.strip()

            # Discount / Description
            # Look for text blocks
            texts = list(card.stripped_strings)
            # texts might be ['Title', 'Description', 'S/ 100', ...]
            
            desc = " ".join(texts)
            
            # Link - usually wrapping the card or inside
            link = card.find('a', href=True)
            original_link = ""
            if link:
                original_link = link['href']
                if not original_link.startswith('http'):
                    original_link = "https://www.bancofalabella.pe" + original_link
            
            all_promos.append({
                'Bank': 'Falabella',
                'Title': title,
                'Discount/Price': '', # Hard to isolate without structure
                'Description': desc,
                'Original_Link': original_link
            })
            
    except Exception as e:
        print(f"Error scraping Falabella: {e}")
    finally:
        driver.quit()
        
    df = pd.DataFrame(all_promos)
    df.to_csv('src/falabella_promos.csv', index=False, encoding='utf-8-sig')
    print(f"Saved {len(all_promos)} Falabella promotions to src/falabella_promos.csv")

if __name__ == "__main__":
    scrape_falabella()
