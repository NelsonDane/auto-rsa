const array_all  = Array.from(document.querySelector('tbody').querySelectorAll('tr'));
const data = [];
for (let i = 0; i < array_all.length; i++) {
    let curr = Array.from(array_all[i].querySelectorAll('td'));
    let name = curr[1].textContent.match(/([A-Z]+),popup/)[1];
    let amount = curr[3].textContent.replace(/\n/g, '').match(/-?\d+(\.\d+)?/)[0];
    let price = curr[4].textContent.replace(/\n/g, '').match(/-?\d+(\.\d+)?/)[0];
    let my_value = curr[5].textContent.replace(/\n/g, '').match(/-?\d+(\.\d+)?/)[0];
    data[i] = [name,amount,price,my_value];
}


'''
    for account in range(accounts):
        try:
            # choose account
            open_dropdown = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='dropdown2']"))
            )
            open_dropdown.click()
            driver.execute_script(
                "document.getElementById('dropdownlist2').getElementsByTagName('li')["
                + str(account)
                + "].click()"
            )
        except:
            print("could not change account")
            killSeleniumDriver(WELLSFARGO_o)
'''