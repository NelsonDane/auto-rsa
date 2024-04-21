## How to Set Up Robinhood 2FA
This guide will show you how to get your Robinhood TOTP secret, which is required for this bot to work if you have 2FA enabled.

Note: Be sure to save your TOTP secret to an authenticator app so you don't get locked out of your account!

1. Download a TOTP app. I recommend [Authy](https://authy.com/).
2. Open the Robinhood app and go to your profile, then the 3 lines in the top left, then Security and privacy, then Two-factor authentication.
3. Click "Set up" for "Authenticator App." Robinhood will show you a setup key. This is what you want to use as your TOTP secret in your `.env` file.
4. Open Authy and click the `+` button to add a new account.
5. Select `Enter key manually` and enter the TOTP secret from step 3.
6. Done! Now use the TOTP secret from step 3 as your `ROBINHOOD_TOTP` in your `.env` file.