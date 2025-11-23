from patreon_auth_selenium import PatreonAuthSelenium
from bs4 import BeautifulSoup
import time

auth = PatreonAuthSelenium(headless=False)
auth.login()

url = "https://www.patreon.com/c/zogarth/posts"
auth.driver.get(url)
time.sleep(5)

soup = BeautifulSoup(auth.driver.page_source, 'html.parser')

# Find all divs with id containing "render"
print("Looking for render elements...")
for elem in soup.find_all(['div', 'main', 'section'], limit=50):
    elem_id = elem.get('id', '')
    if 'render' in elem_id.lower():
        print(f"Found: {elem.name} with id='{elem_id}'")

# Look for header elements
print("\nLooking for header elements...")
headers = soup.find_all('header', limit=10)
for i, header in enumerate(headers):
    print(f"Header {i+1}:")
    # Find picture in this header
    picture = header.find('picture')
    if picture:
        img = picture.find('img')
        if img and img.get('src'):
            print(f"  Found image: {img['src'][:100]}...")
    else:
        print("  No picture found")

auth.driver.quit()
