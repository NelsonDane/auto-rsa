## How to Log in to Webull
This will guide you on how to get the Webull access token that is required for this bot to work.

1. Go to [Webull](https://app.webull.com/login) and log in with your email and password. DO NOT USE THE QR CODE TO LOGIN.
2. Right click anywhere on the page and click `Inspect`.
3. Go to the `Network` tab.
4. In the filter/search bar, type `v2`. You may need to refresh the page.
5. Click on the first result, and then click on the `Headers` tab.
6. Scroll down to the `Request Headers` section and copy the `Access_token` header.
7. Done! Now use the access token you copied as your `WEBULL_ACCESS_TOKEN` in your `.env` file.
