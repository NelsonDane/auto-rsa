## How to Get Schwab 2FA Secret
This guide will show you how to get your Schwab TOTP secret, which is required for this bot to work if you have 2FA enabled.

Note: basically what we're doing is creating a new TOTP code, then adding it to Schwab and this program. That way, the generated code will be the same for both.

1. Download a TOTP app. I recommend [Authy](https://authy.com/).
2. cd into the `guides` folder, then run `python schwab2fa.py`, copying the symantec ID and the TOTP secret.
3. Open Authy and click the `+` button to add a new account.
4. Select `Enter key manually` and enter the TOTP secret from step 2.
5. Log in to the Schwab [security center](https://client.schwab.com/app/access/securitysettings/#/security/verification)
6. Under Two-Step Verification, select Always at Login, and then select "Security Token" as your method.
7. Enter the Symantec ID from step 2 into the Credential ID field.
8. Enter the 6-digit code from Authy into the Security Code field.
9. Done! Now use the TOTP secret from step 2 as your `SCHWAB_TOTP_SECRET` in your `.env` file.

If you have any issues, check the guide by the author of the API [here](https://github.com/itsjafer/schwab-api#create-a-totp-authentication-token).