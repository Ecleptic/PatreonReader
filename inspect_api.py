#!/usr/bin/env python3
"""
Intercept network requests to see how Patreon loads posts.
"""

from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import json
import time

# Enable performance logging
caps = DesiredCapabilities.CHROME
caps['goog:loggingPrefs'] = {'performance': 'ALL'}

chrome_options = Options()
chrome_options.add_argument('--headless=new')
chrome_options.add_argument(f'user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options, desired_capabilities=caps)

# Navigate to a Patreon page
print("Loading Patreon page...")
driver.get('https://www.patreon.com/c/zogarth/posts')
time.sleep(5)

# Get performance logs
print("\nFetching network requests...")
logs = driver.get_log('performance')

api_calls = []
for entry in logs:
    log = json.loads(entry['message'])['message']
    if 'Network.response' in log['method'] or 'Network.request' in log['method']:
        try:
            if 'params' in log and 'request' in log['params']:
                url = log['params']['request']['url']
                if 'patreon.com/api' in url and 'post' in url.lower():
                    api_calls.append(url)
        except:
            pass

print(f"\nFound {len(api_calls)} API calls related to posts:")
for call in set(api_calls[:10]):
    print(f"  {call}")

driver.quit()
