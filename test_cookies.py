#!/usr/bin/env python3
import browser_cookie3
import json

print("Loading Firefox cookies...")
cookies = browser_cookie3.firefox(domain_name="instagram.com")
cookie_dict = {}

for cookie in cookies:
    if "instagram.com" in cookie.domain:
        print(f"Found cookie: {cookie.name} for {cookie.domain}")
        cookie_dict[cookie.name] = cookie.value

if "sessionid" in cookie_dict:
    print("\nFound Instagram session cookie!")
    # Save cookies to a file that gallery-dl can read
    with open("gallery-dl-cookies.txt", "w") as f:
        json.dump({"instagram": cookie_dict}, f, indent=4)
    print("\nCookies saved to gallery-dl-cookies.txt")
else:
    print("\nNo Instagram session cookie found!")
